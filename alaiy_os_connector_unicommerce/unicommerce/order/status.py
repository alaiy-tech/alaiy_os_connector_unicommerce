# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Poll Unicommerce for order/shipment status changes and mirror them onto ERPNext,
triggering cancellations and returns as needed."""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.manifest import search_shipping_packages
from alaiy_os_connector_unicommerce.unicommerce.client.orders import search_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ORDER_CODE_FIELD, ORDER_SHIPMENT_STATUS_FIELD, ORDER_STATUS_FIELD, SETTINGS_DOCTYPE,
    SHIPPING_PACKAGE_CODE_FIELD, SHIPPING_PACKAGE_STATUS_FIELD,
)
from alaiy_os_connector_unicommerce.unicommerce.order.cancellation import (
    check_and_update_customer_initiated_returns, create_rto_return, fully_cancel_orders,
    update_partially_cancelled_orders,
)

PARTIAL_CANCELLED_STATES = ["PENDING_VERIFICATION", "CREATED", "PROCESSING"]
RETURN_POSSIBLE_STATE = ["COMPLETE"]
SHIPMENT_RETURN_STATES = ["RETURN_EXPECTED", "RETURNED"]


def update_sales_order_status():
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return

    client = UnicommerceClient()

    days_to_sync = min(settings.get("order_status_days") or 2, 14)
    minutes = days_to_sync * 24 * 60
    updated_orders = search_sales_order(client, updated_since=minutes) or []

    enabled_channels = frappe.db.get_list("Unicommerce Channel", filters={"enabled": 1}, pluck="channel_id")
    valid_orders = [order for order in updated_orders if order.get("channel") in enabled_channels]
    if not valid_orders:
        return

    _update_order_status_fields(valid_orders)

    # Each stage below is independent -- a real order in one stage failing
    # (a malformed return, an API hiccup) must not block the OTHER stages for
    # every other order in this same run. Confirmed live this class of bug
    # was silently dropping real Unicommerce returns (see
    # prepare_delivery_note's matching fix and its docstring for the RTO
    # case) -- a single unhandled exception here would also have skipped
    # invoice generation for every other newly-completed order in the batch.
    fully_cancelled_orders = [d["code"] for d in valid_orders if d["status"] == "CANCELLED"]
    if fully_cancelled_orders:
        try:
            fully_cancel_orders(fully_cancelled_orders)
        except Exception:
            frappe.log_error(title="Unicommerce: fully_cancel_orders failed", message=frappe.get_traceback())

    probable_partial_cancels = [d for d in valid_orders if d["status"] in PARTIAL_CANCELLED_STATES]
    if probable_partial_cancels:
        try:
            update_partially_cancelled_orders(probable_partial_cancels, client=client)
        except Exception:
            frappe.log_error(
                title="Unicommerce: update_partially_cancelled_orders failed", message=frappe.get_traceback()
            )

    probable_returns = [d for d in valid_orders if d["status"] in RETURN_POSSIBLE_STATE]
    if probable_returns:
        try:
            check_and_update_customer_initiated_returns(probable_returns, client=client)
        except Exception:
            frappe.log_error(
                title="Unicommerce: check_and_update_customer_initiated_returns failed",
                message=frappe.get_traceback(),
            )

    if settings.get("auto_generate_invoice"):
        newly_completed = [d["code"] for d in valid_orders if d["status"] in RETURN_POSSIBLE_STATE]
        if newly_completed:
            try:
                _generate_invoices_for_newly_completed_orders(newly_completed)
            except Exception:
                frappe.log_error(
                    title="Unicommerce: _generate_invoices_for_newly_completed_orders failed",
                    message=frappe.get_traceback(),
                )


def _generate_invoices_for_newly_completed_orders(order_codes):
    """Orders that just turned COMPLETE and have no Sales Invoice yet -- skip
    ones already invoiced (manually or by an earlier run) so this is safe to
    call every hourly_long tick without duplicating invoices."""
    from alaiy_os_connector_unicommerce.unicommerce.fulfillment.invoice import bulk_generate_invoices

    orders = frappe.db.get_values(
        "Sales Order", {ORDER_CODE_FIELD: ("in", order_codes)},
        fieldname=["name", ORDER_CODE_FIELD], as_dict=True,
    )
    if not orders:
        return

    invoiced_uni_codes = frappe.db.get_all(
        "Sales Invoice", filters={ORDER_CODE_FIELD: ("in", [d[ORDER_CODE_FIELD] for d in orders])},
        pluck=ORDER_CODE_FIELD,
    )
    pending = [d["name"] for d in orders if d[ORDER_CODE_FIELD] not in invoiced_uni_codes]
    if pending:
        bulk_generate_invoices(pending)


def _update_order_status_fields(orders):
    order_status_map = {d["code"]: d["status"] for d in orders}
    order_codes = list(order_status_map.keys())

    current_orders_status = frappe.db.get_values(
        "Sales Order", {ORDER_CODE_FIELD: ("in", order_codes)},
        fieldname=["name", ORDER_STATUS_FIELD, ORDER_CODE_FIELD], as_dict=True,
    )

    for order in current_orders_status:
        old_status = order.get(ORDER_STATUS_FIELD)
        new_status = order_status_map.get(order.get(ORDER_CODE_FIELD))
        if old_status != new_status:
            frappe.db.set_value("Sales Order", order["name"], ORDER_STATUS_FIELD, new_status)


def ignore_pick_list_on_sales_order_cancel(doc, method=None):
    """Sales Order on_cancel: ignore Pick List doctype links so cancellation isn't blocked."""
    ignored_links = list(doc.ignore_linked_doctypes or [])
    ignored_links.append("Pick List")
    doc.ignore_linked_doctypes = ignored_links


def update_shipping_package_status():
    """Periodically pull changed shipping package info into ERPNext."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return

    client = UnicommerceClient()

    days_to_sync = min(settings.get("order_status_days") or 2, 14)
    minutes = days_to_sync * 24 * 60

    enabled_facilities = list(settings.get_integration_to_erpnext_wh_mapping().keys())
    enabled_channels = frappe.db.get_list("Unicommerce Channel", filters={"enabled": 1}, pluck="channel_id")

    for facility in enabled_facilities:
        updated_packages = search_shipping_packages(client, updated_since=minutes, facility_code=facility) or []
        valid_packages = [p for p in updated_packages if p.get("channel") in enabled_channels]
        if not valid_packages:
            continue

        _update_package_status_fields(valid_packages)
        _track_order_shipment_status(valid_packages)

        returning_packages = [p for p in valid_packages if p["status"] in SHIPMENT_RETURN_STATES]
        for package in returning_packages:
            try:
                create_rto_return(package, client=client)
            except Exception:
                frappe.log_error(
                    title=f"Unicommerce: create_rto_return failed for package {package.get('code')}",
                    message=frappe.get_traceback(),
                )
                continue


def _track_order_shipment_status(packages):
    """Write shipment status straight onto Sales Order, independent of
    whether the order has a local Sales Invoice yet -- unlike
    _update_package_status_fields (which only ever reaches invoiced orders
    via Sales Invoice), this is the only place a never-invoiced order's real
    shipment/return progress becomes visible in ERPNext at all."""
    packages_with_order = [p for p in packages if p.get("saleOrderCode")]
    if not packages_with_order:
        return

    order_shipment_status_map = {}
    for package in packages_with_order:
        order_shipment_status_map[package["saleOrderCode"]] = package["status"]

    current = frappe.db.get_values(
        "Sales Order", {ORDER_CODE_FIELD: ("in", list(order_shipment_status_map.keys()))},
        fieldname=["name", ORDER_SHIPMENT_STATUS_FIELD, ORDER_CODE_FIELD], as_dict=True,
    )
    for order in current:
        new_status = order_shipment_status_map.get(order.get(ORDER_CODE_FIELD))
        if order.get(ORDER_SHIPMENT_STATUS_FIELD) != new_status:
            frappe.db.set_value("Sales Order", order["name"], ORDER_SHIPMENT_STATUS_FIELD, new_status)


def _update_package_status_fields(packages):
    package_status_map = {d["code"]: d["status"] for d in packages}
    package_codes = list(package_status_map.keys())

    current_package_status = frappe.db.get_values(
        "Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: ("in", package_codes)},
        fieldname=["name", SHIPPING_PACKAGE_STATUS_FIELD, SHIPPING_PACKAGE_CODE_FIELD], as_dict=True,
    )

    for invoice in current_package_status:
        old_status = invoice.get(SHIPPING_PACKAGE_STATUS_FIELD)
        new_status = package_status_map.get(invoice.get(SHIPPING_PACKAGE_CODE_FIELD))
        if old_status != new_status:
            frappe.db.set_value("Sales Invoice", invoice["name"], SHIPPING_PACKAGE_STATUS_FIELD, new_status)
