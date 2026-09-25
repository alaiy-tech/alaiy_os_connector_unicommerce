# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Auto-create Delivery Notes when Unicommerce reports a shipment dispatched."""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.manifest import search_shipping_packages
from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ORDER_CODE_FIELD, ORDER_DISPLAY_CODE_FIELD, SETTINGS_DOCTYPE, SHIPPING_PACKAGE_CODE_FIELD,
    UNICOMMERCE_SHIPPING_ID,
)

#: A package at or past this point has definitely left the warehouse --
#: DISPATCHED is what the routine 5-minute job catches at the moment it
#: happens; by the time a stale order is old enough for the catch-up below
#: to reach it, the same package may already show DELIVERED. Either one is
#: still a real, un-recorded shipment.
DISPATCHED_OR_LATER = ("DISPATCHED", "DELIVERED")

#: Same reasoning as order/status.py's STALE_ORDER_BATCH/STALE_ORDER_DAYS:
#: a fixed batch of the oldest candidates per day, old enough that the
#: routine 5-minute job (capped at order_status_days, min(setting, 14)) has
#: certainly already given up on them.
STALE_DELIVERY_BATCH = 500
STALE_DELIVERY_DAYS = 14


@frappe.whitelist()
def prepare_delivery_note(days_to_sync_override: int | None = None):
    """Auto-create a Delivery Note for every dispatched Unicommerce package.

    One order's failure (e.g. NegativeStockError because Bin is short of the
    real quantity) must never block every OTHER order behind it in the same
    run -- confirmed live this was happening: the try/except used to wrap the
    whole function, so a single bad item aborted the entire batch silently,
    every single run, until that one item was fixed. Each order now gets its
    own try/except so the rest of the batch always completes.

    The routine 5-minute cron always stays capped at 14 days -- widening that
    would multiply this job's Unicommerce API calls by however much further
    back it looked, every single run, forever. But the cap has a real cost:
    a Sales Order whose Delivery Note isn't created within that window (its
    Sales Invoice arrived late, a transient failure, or it shipped before
    this job existed) is skipped every run after and NEVER revisited, since
    the search itself only asks Unicommerce for packages updated within the
    window. That order's stock stays reserved (`Bin.reserved_qty`) forever,
    which is exactly the "Reserved inventory is far higher than actual
    demand" symptom -- an accumulation of these across enough old orders
    outweighs whatever's genuinely awaiting dispatch today.

    `days_to_sync_override` exists for that: a one-off wider catch-up run,
    not the automatic schedule. Run it by hand, e.g.:
        bench --site <site> execute alaiy_os_connector_unicommerce.unicommerce.fulfillment.delivery_note.prepare_delivery_note --kwargs '{"days_to_sync_override": 90}'
    """
    try:
        settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
        if not settings.delivery_note:
            return

        client = UnicommerceClient()
        days_to_sync = days_to_sync_override or min(settings.get("order_status_days") or 2, 14)
        minutes = days_to_sync * 24 * 60

        enabled_facilities = list(settings.get_integration_to_erpnext_wh_mapping().keys())
        enabled_channels = frappe.db.get_list("Unicommerce Channel", filters={"enabled": 1}, pluck="channel_id")
    except Exception:
        frappe.log_error(title="Unicommerce: prepare_delivery_note setup failed", message=frappe.get_traceback())
        return

    for facility in enabled_facilities:
        try:
            updated_packages = search_shipping_packages(client, updated_since=minutes, facility_code=facility) or []
        except Exception:
            frappe.log_error(
                title=f"Unicommerce: prepare_delivery_note failed to fetch packages for facility {facility}",
                message=frappe.get_traceback(),
            )
            continue

        valid_packages = [p for p in updated_packages if p.get("channel") in enabled_channels]
        shipped_packages = [p for p in valid_packages if p["status"] == "DISPATCHED"]

        for order in shipped_packages:
            try:
                if frappe.db.exists("Delivery Note", {UNICOMMERCE_SHIPPING_ID: order["code"]}):
                    continue
                if not frappe.db.exists("Sales Order", {ORDER_CODE_FIELD: order["saleOrderCode"]}):
                    continue

                sales_order = frappe.get_doc("Sales Order", {ORDER_CODE_FIELD: order["saleOrderCode"]})
                if not frappe.db.exists("Sales Invoice", {ORDER_CODE_FIELD: sales_order.get(ORDER_CODE_FIELD)}):
                    continue

                sales_invoice = frappe.get_doc(
                    "Sales Invoice", {ORDER_CODE_FIELD: sales_order.get(ORDER_CODE_FIELD)}
                )
                create_delivery_note(sales_order, sales_invoice)
                frappe.db.commit()
            except Exception:
                frappe.db.rollback()
                frappe.log_error(
                    title=f"Unicommerce: could not create Delivery Note for package {order.get('code')}",
                    message=frappe.get_traceback(),
                )
                continue


def create_delivery_note(so, sales_invoice):
    from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

    res = make_delivery_note(source_name=so.name)
    res.set(ORDER_CODE_FIELD, sales_invoice.get(ORDER_CODE_FIELD))
    # Prefer the Sales Order (authoritative, backfilled) and fall back to the invoice.
    res.set(ORDER_DISPLAY_CODE_FIELD, so.get(ORDER_DISPLAY_CODE_FIELD) or sales_invoice.get(ORDER_DISPLAY_CODE_FIELD))
    res.set(UNICOMMERCE_SHIPPING_ID, sales_invoice.get(SHIPPING_PACKAGE_CODE_FIELD))
    res.flags.ignore_permissions = True
    # Unicommerce already reported this package DISPATCHED -- the item
    # physically left the warehouse in reality, in the past. That makes
    # NegativeStockError the wrong guard here: it exists to stop a FUTURE
    # oversell, but this is recording a shipment that has already
    # unavoidably happened. Confirmed live: ERPNext's Bin can lag Unicommerce
    # on inbound receipts (a real item, COWMATBLK, showed 0 stock on both
    # sides after this exact package's dispatch), and refusing to record the
    # shipment over that gap doesn't undo the shipment -- it just leaves
    # ERPNext's own records silently missing a real, already-completed
    # Delivery Note. Scoped to this document only, not a global setting.
    res.flags.ignore_negative_stock = True
    res.insert()
    res.submit()
    return res


def catch_up_on_stale_deliveries():
    """Daily sweep for invoiced orders whose Delivery Note fell out of
    prepare_delivery_note's own capped window before it was ever created.

    prepare_delivery_note's own docstring already names this gap: its
    5-minute cron only ever asks Unicommerce for packages updated within
    `order_status_days` (min(setting, 14)) minutes, so an order whose
    dispatch update falls outside that window before the job happens to run
    is skipped every run after and never revisited -- its stock stays
    reserved (`Bin.reserved_qty`) forever. The only fix that existed for
    this was `days_to_sync_override`, a manual one-off `bench execute`, not
    an automatic catch-up -- same gap, same shape as
    order/status.py's `catch_up_on_stale_orders`, which this mirrors.

    Candidates are invoiced Sales Orders with no Delivery Note yet, oldest
    `modified` first -- old enough that the routine job has certainly
    already given up on them. Each one gets ONE direct get_sales_order call
    to read its CURRENT shipping-package status, independent of whatever
    window or `updated_since` search the routine job used.

    Bounded and resumable like the other catch-up jobs: a fixed batch per
    run, each one's `modified` moving it out of the next run's "oldest"
    query, whether or not a Delivery Note actually gets created for it.
    """
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.delivery_note:
        return {"skipped": "delivery note sync not enabled"}

    candidates = frappe.db.sql(
        f"""
        SELECT so.name AS so_name, so.`{ORDER_CODE_FIELD}` AS order_code
        FROM `tabSales Order` so
        JOIN `tabSales Invoice` si
          ON si.`{ORDER_CODE_FIELD}` = so.`{ORDER_CODE_FIELD}` AND si.is_return = 0 AND si.docstatus = 1
        WHERE so.docstatus = 1
          AND so.`{ORDER_CODE_FIELD}` IS NOT NULL AND so.`{ORDER_CODE_FIELD}` != ''
          AND so.modified < DATE_SUB(NOW(), INTERVAL %(stale_days)s DAY)
          AND NOT EXISTS (
              SELECT 1 FROM `tabDelivery Note` dn
              WHERE dn.`{ORDER_CODE_FIELD}` = so.`{ORDER_CODE_FIELD}` AND dn.docstatus = 1
          )
        ORDER BY so.modified ASC
        LIMIT %(batch_size)s
        """,
        {"stale_days": STALE_DELIVERY_DAYS, "batch_size": STALE_DELIVERY_BATCH},
        as_dict=True,
    )
    if not candidates:
        return {"orders": 0, "created": 0, "failed": 0}

    client = UnicommerceClient()
    created = failed = 0
    for row in candidates:
        try:
            so_data = get_sales_order(client, row.order_code)
            if so_data and any(
                p.get("status") in DISPATCHED_OR_LATER for p in so_data.get("shippingPackages", [])
            ):
                sales_order = frappe.get_doc("Sales Order", row.so_name)
                sales_invoice = frappe.get_doc(
                    "Sales Invoice", {ORDER_CODE_FIELD: row.order_code, "is_return": 0, "docstatus": 1}
                )
                if not frappe.db.exists(
                    "Delivery Note", {UNICOMMERCE_SHIPPING_ID: sales_invoice.get(SHIPPING_PACKAGE_CODE_FIELD)}
                ):
                    create_delivery_note(sales_order, sales_invoice)
                    created += 1
            frappe.db.commit()
        except Exception:
            failed += 1
            frappe.db.rollback()
            frappe.log_error(
                title=f"Unicommerce: stale-delivery catch-up failed for {row.so_name}",
                message=frappe.get_traceback(),
            )

    return {"orders": len(candidates), "created": created, "failed": failed}
