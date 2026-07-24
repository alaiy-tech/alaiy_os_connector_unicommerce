# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Auto-create Delivery Notes when Unicommerce reports a shipment dispatched."""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.manifest import search_shipping_packages
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ORDER_CODE_FIELD, ORDER_DISPLAY_CODE_FIELD, SETTINGS_DOCTYPE, SHIPPING_PACKAGE_CODE_FIELD,
    UNICOMMERCE_SHIPPING_ID,
)


@frappe.whitelist()
def prepare_delivery_note():
    try:
        settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
        if not settings.delivery_note:
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

            shipped_packages = [p for p in valid_packages if p["status"] == "DISPATCHED"]
            for order in shipped_packages:
                if frappe.db.exists("Delivery Note", {UNICOMMERCE_SHIPPING_ID: order["code"]}):
                    continue
                if not frappe.db.exists("Sales Order", {ORDER_CODE_FIELD: order["saleOrderCode"]}):
                    continue

                sales_order = frappe.get_doc("Sales Order", {ORDER_CODE_FIELD: order["saleOrderCode"]})
                if frappe.db.exists("Sales Invoice", {ORDER_CODE_FIELD: sales_order.get(ORDER_CODE_FIELD)}):
                    sales_invoice = frappe.get_doc(
                        "Sales Invoice", {ORDER_CODE_FIELD: sales_order.get(ORDER_CODE_FIELD)}
                    )
                    create_delivery_note(sales_order, sales_invoice)
    except Exception:
        frappe.log_error(title="Unicommerce: prepare_delivery_note failed", message=frappe.get_traceback())


def create_delivery_note(so, sales_invoice):
    from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

    res = make_delivery_note(source_name=so.name)
    res.set(ORDER_CODE_FIELD, sales_invoice.get(ORDER_CODE_FIELD))
    # Prefer the Sales Order (authoritative, backfilled) and fall back to the invoice.
    res.set(ORDER_DISPLAY_CODE_FIELD, so.get(ORDER_DISPLAY_CODE_FIELD) or sales_invoice.get(ORDER_DISPLAY_CODE_FIELD))
    res.set(UNICOMMERCE_SHIPPING_ID, sales_invoice.get(SHIPPING_PACKAGE_CODE_FIELD))
    res.flags.ignore_permissions = True
    res.insert()
    res.submit()
    return res
