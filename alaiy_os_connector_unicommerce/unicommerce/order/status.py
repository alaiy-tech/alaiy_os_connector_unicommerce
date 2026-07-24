# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Poll Unicommerce for order/shipment status changes and mirror them onto ERPNext,
triggering cancellations and returns as needed."""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.manifest import search_shipping_packages
from alaiy_os_connector_unicommerce.unicommerce.client.orders import search_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ORDER_CODE_FIELD, ORDER_STATUS_FIELD, SETTINGS_DOCTYPE, SHIPPING_PACKAGE_CODE_FIELD,
    SHIPPING_PACKAGE_STATUS_FIELD,
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

    fully_cancelled_orders = [d["code"] for d in valid_orders if d["status"] == "CANCELLED"]
    if fully_cancelled_orders:
        fully_cancel_orders(fully_cancelled_orders)

    probable_partial_cancels = [d for d in valid_orders if d["status"] in PARTIAL_CANCELLED_STATES]
    if probable_partial_cancels:
        update_partially_cancelled_orders(probable_partial_cancels, client=client)

    probable_returns = [d for d in valid_orders if d["status"] in RETURN_POSSIBLE_STATE]
    if probable_returns:
        check_and_update_customer_initiated_returns(probable_returns, client=client)


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
            frappe.db.set_value("Sales Order", order["name"], ORDER_STATUS_FIELD, new_status, for_update=True)


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

        returning_packages = [p for p in valid_packages if p["status"] in SHIPMENT_RETURN_STATES]
        for package in returning_packages:
            create_rto_return(package, client=client)


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
            frappe.db.set_value("Sales Invoice", invoice["name"], SHIPPING_PACKAGE_STATUS_FIELD, new_status, for_update=True)
