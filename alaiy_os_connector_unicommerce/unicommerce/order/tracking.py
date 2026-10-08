# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Airway bill (tracking number), courier and tracking link from Unicommerce
shipping packages onto the Sales Order and its Sales Invoices.

The package search used by the frequent status poll returns the tracking number
and courier but not the tracking link; the link only comes with the full sale
order (or package details), so the poll fetches the full order for the few
orders whose stored values differ."""

import frappe
from frappe.utils import now_datetime

from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ORDER_CODE_FIELD,
    ORDER_DELIVERED_ON_FIELD,
    ORDER_SHIPMENT_STATUS_FIELD,
    SHIPPING_PACKAGE_CODE_FIELD,
    SHIPPING_PROVIDER_CODE,
    TRACKING_CODE_FIELD,
    TRACKING_LINK_FIELD,
)
from alaiy_os_connector_unicommerce.unicommerce.order.details import (
    PACKAGE_FIELDS,
    apply_order_details,
    package_values,
)
from alaiy_os_connector_unicommerce.unicommerce.utils import get_unicommerce_datetime

TRACKING_FIELDS = [TRACKING_CODE_FIELD, TRACKING_LINK_FIELD, SHIPPING_PROVIDER_CODE, *[f[0] for f in PACKAGE_FIELDS]]

#: Full-order fetches one poll run may spend on tracking. Only orders whose
#: stored tracking differs from what Unicommerce reports are fetched, so a
#: backlog clears over a few runs instead of one long one.
TRACKING_FETCHES_PER_RUN = 25


def package_tracking(package):
    return {
        **package_values(package),
        TRACKING_CODE_FIELD: package.get("trackingNumber"),
        TRACKING_LINK_FIELD: package.get("trackingLink"),
        SHIPPING_PROVIDER_CODE: (
            package.get("shippingProvider") or package.get("shippingProviderCode") or package.get("shippingCourier")
        ),
    }


def _write(doctype, name, current, values):
    # Only real values, only when different: an empty value from Unicommerce
    # never wipes what is already stored.
    changed = {k: v for k, v in values.items() if v and (current or {}).get(k) != v}
    if changed:
        frappe.db.set_value(doctype, name, changed)


def apply_order_tracking(so_name, so_data):
    """Refresh the order and line details of a Sales Order from a full sale
    order payload, then write tracking and shipment details onto the Sales
    Order (its furthest-along package that has an airway bill) and onto each
    Sales Invoice, by shipping package."""
    from alaiy_os_connector_unicommerce.unicommerce.order.status import SHIPMENT_STATUS_RANK

    apply_order_details(so_name, so_data)

    # Every package counts, not only ones with an airway bill: the amount to
    # collect, weights and statuses exist from the moment a package is created.
    packages = [p for p in so_data.get("shippingPackages") or [] if p.get("code")]
    if not packages:
        return

    def rank(package):
        return SHIPMENT_STATUS_RANK.get(package.get("status"), 0)

    furthest = max(packages, key=rank)
    # The Sales Order shows the furthest package that has an airway bill, when
    # there is one, so a tracking number is never hidden behind a package that
    # has none yet.
    best = max([p for p in packages if p.get("trackingNumber")] or packages, key=rank)

    values = package_tracking(best)
    values[ORDER_SHIPMENT_STATUS_FIELD] = furthest.get("status")
    if furthest.get("status") == "DELIVERED":
        values[ORDER_DELIVERED_ON_FIELD] = get_unicommerce_datetime(furthest.get("delivered"))
    current = frappe.db.get_value(
        "Sales Order", so_name, [*TRACKING_FIELDS, ORDER_SHIPMENT_STATUS_FIELD, ORDER_DELIVERED_ON_FIELD], as_dict=True
    )
    _write("Sales Order", so_name, current, values)

    by_code = {p["code"]: p for p in packages}
    invoices = frappe.db.get_values(
        "Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: ("in", list(by_code))},
        fieldname=["name", SHIPPING_PACKAGE_CODE_FIELD, *TRACKING_FIELDS], as_dict=True,
    )
    for invoice in invoices:
        _write("Sales Invoice", invoice["name"], invoice, package_tracking(by_code[invoice[SHIPPING_PACKAGE_CODE_FIELD]]))


def refresh_tracking_from_packages(packages, client):
    """Status poll: for orders whose package now carries a tracking number
    that is not stored yet (or whose link is still missing), fetch the full
    order and apply its tracking."""
    reported = {
        p["saleOrderCode"]: p["trackingNumber"] for p in packages if p.get("trackingNumber") and p.get("saleOrderCode")
    }
    if not reported:
        return

    orders = frappe.db.get_values(
        "Sales Order", {ORDER_CODE_FIELD: ("in", list(reported))},
        fieldname=["name", ORDER_CODE_FIELD, TRACKING_CODE_FIELD, TRACKING_LINK_FIELD], as_dict=True,
    )
    stale = [
        o for o in orders
        if not o.get(TRACKING_LINK_FIELD) or o.get(TRACKING_CODE_FIELD) != reported[o[ORDER_CODE_FIELD]]
    ]
    for order in stale[:TRACKING_FETCHES_PER_RUN]:
        try:
            so_data = get_sales_order(client, order[ORDER_CODE_FIELD])
            if so_data:
                apply_order_tracking(order["name"], so_data)
        except Exception:
            frappe.log_error(
                title=f"Unicommerce: tracking refresh failed for {order['name']}", message=frappe.get_traceback()
            )


#: Orders one hourly run fetches in full. Newest first, so recent orders are
#: complete first and older history fills in over the following days.
MISSING_DETAILS_BATCH = 50

_SHIPPED_STATUSES = (
    "DISPATCHED", "SHIPPED", "DELIVERED", "RETURN_EXPECTED", "RETURNED", "RETURN_ACKNOWLEDGED",
)


def fill_missing_order_details():
    """Hourly background fill. Fetches the full order for every Sales Order
    whose details were never applied, plus shipped orders that still have no
    airway bill (re-checked at most once a day), and applies them through the
    same path as the live poll. Bounded and resumable: it commits per order
    and a failed fetch is retried the next day."""
    from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
    from alaiy_os_connector_unicommerce.unicommerce.constants import (
        ORDER_SHIPMENT_STATUS_FIELD,
        ORDER_STATUS_FIELD,
        SETTINGS_DOCTYPE,
    )
    from alaiy_os_connector_unicommerce.unicommerce.order.details import (
        DETAILS_ATTEMPTED_FIELD,
        DETAILS_SYNCED_FIELD,
    )

    if not frappe.get_cached_doc(SETTINGS_DOCTYPE).is_enabled:
        return {"skipped": "connector not enabled"}

    rows = frappe.db.sql(
        f"""
        SELECT name, `{ORDER_CODE_FIELD}` AS order_code
        FROM `tabSales Order`
        WHERE docstatus = 1
          AND COALESCE(`{ORDER_CODE_FIELD}`, '') != ''
          AND COALESCE(`{ORDER_STATUS_FIELD}`, '') != 'CANCELLED'
          AND (`{DETAILS_ATTEMPTED_FIELD}` IS NULL OR `{DETAILS_ATTEMPTED_FIELD}` < DATE_SUB(NOW(), INTERVAL 1 DAY))
          AND (
            `{DETAILS_SYNCED_FIELD}` IS NULL
            OR (
              COALESCE(`{TRACKING_CODE_FIELD}`, '') = ''
              AND `{ORDER_SHIPMENT_STATUS_FIELD}` IN %(shipped)s
              AND `{DETAILS_SYNCED_FIELD}` < DATE_SUB(NOW(), INTERVAL 1 DAY)
            )
          )
        ORDER BY (`{DETAILS_ATTEMPTED_FIELD}` IS NULL) DESC, creation DESC
        LIMIT %(batch)s
        """,
        {"shipped": _SHIPPED_STATUSES, "batch": MISSING_DETAILS_BATCH},
        as_dict=True,
    )
    if not rows:
        return {"orders": 0, "filled": 0, "failed": 0}

    client = UnicommerceClient()
    filled = failed = 0
    for row in rows:
        try:
            # Stamped before the fetch and committed either way, so a fetch that
            # fails is not retried until tomorrow and cannot starve newer orders.
            frappe.db.set_value("Sales Order", row.name, DETAILS_ATTEMPTED_FIELD, now_datetime(), update_modified=False)
            so_data = get_sales_order(client, row.order_code)
            if not so_data:
                failed += 1
                frappe.db.commit()
                continue
            apply_order_tracking(row.name, so_data)
            filled += 1
            frappe.db.commit()
        except Exception:
            failed += 1
            frappe.db.rollback()
            frappe.log_error(
                title=f"Unicommerce: filling order details failed for {row.name}", message=frappe.get_traceback()
            )

    if failed == len(rows):
        frappe.log_error(
            title="Unicommerce: no order details could be fetched",
            message="Every full-order fetch in this run came back empty or failed; check the API user's access.",
        )
    return {"orders": len(rows), "filled": filled, "failed": failed}
