# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Sync order cancellations and customer/RTO returns from Unicommerce into ERPNext."""

import json
from collections import defaultdict
from datetime import date, datetime

import frappe
from erpnext.accounts.doctype.sales_invoice.mapper import make_sales_return
from erpnext.accounts.services.child_item_update import update_child_qty_rate

from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    CHANNEL_ID_FIELD, FACILITY_CODE_FIELD, ORDER_CODE_FIELD, ORDER_ITEM_CODE_FIELD, ORDER_STATUS_FIELD,
    RETURN_CODE_FIELD, SHIPPING_PACKAGE_CODE_FIELD, SHIPPING_PROVIDER_CODE, TRACKING_CODE_FIELD,
)


def fully_cancel_orders(unicommerce_order_codes: list[str]) -> None:
    """Cancel ERPNext Sales Orders that were fully cancelled in Unicommerce."""
    current_orders_status = frappe.db.get_values(
        "Sales Order",
        {ORDER_CODE_FIELD: ("in", unicommerce_order_codes)},
        fieldname=["name", ORDER_STATUS_FIELD, ORDER_CODE_FIELD, "docstatus"],
        as_dict=True,
    )

    for order in current_orders_status:
        if order.docstatus != 1:
            continue

        linked_sales_invoice = frappe.db.get_value(
            "Sales Invoice", filters={ORDER_CODE_FIELD: order.get(ORDER_CODE_FIELD), "docstatus": 1}
        )
        if not linked_sales_invoice:
            frappe.get_doc("Sales Order", order.name).cancel()


def update_partially_cancelled_orders(orders, client) -> None:
    """Check all recently updated orders for partial cancellations."""
    for order in _filter_recent_orders(orders):
        so_data = get_sales_order(client, order["code"])
        if so_data:
            update_erpnext_order_items(so_data)


def _filter_recent_orders(orders, time_limit=60 * 12):
    """Only consider orders updated within the last `time_limit` minutes."""
    check_timestamp = (datetime.utcnow().timestamp() - time_limit * 60) * 1000
    return [order for order in orders if int(order["updated"]) >= check_timestamp]


def update_erpnext_order_items(so_data, so=None):
    """Remove cancelled line items from the matching ERPNext Sales Order."""
    cancelled_items = [d["code"] for d in so_data["saleOrderItems"] if d["statusCode"] == "CANCELLED"]
    if not cancelled_items:
        return

    if not so:
        so_name = frappe.db.get_value("Sales Order", {ORDER_CODE_FIELD: so_data["code"]})
        if not so_name:
            return
        so = frappe.get_doc("Sales Order", so_name)

    if so.docstatus > 1:
        return

    new_items = _delete_cancelled_items(so.items, cancelled_items)
    if len(so.items) == len(new_items):
        return

    update_child_qty_rate(
        parent_doctype="Sales Order", trans_items=_serialize_items(new_items), parent_doctype_name=so.name,
    )


def _delete_cancelled_items(erpnext_items, cancelled_items):
    items = [d.as_dict() for d in erpnext_items if d.get(ORDER_ITEM_CODE_FIELD) not in cancelled_items]
    for item in items:
        # `docname` mirrors `name`, required by the Update Items call
        item["docname"] = item["name"]
    return items


def _serialize_items(trans_items) -> str:
    for item in trans_items:
        for k, v in item.items():
            if isinstance(v, date | datetime):
                item[k] = str(v)
    return json.dumps(trans_items)


def create_rto_return(package_info, client):
    """Create a draft credit note when a package is expected to be returned to origin."""
    package_code = package_info["code"]

    invoice = frappe.db.get_value(
        "Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: package_code},
        ["name", ORDER_CODE_FIELD, CHANNEL_ID_FIELD], as_dict=True,
    )
    already_returned = frappe.db.get_value("Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: package_code, "is_return": 1})
    if not invoice or already_returned:
        return

    so_data = get_sales_order(client, invoice.get(ORDER_CODE_FIELD))
    rto_returns = [r for r in so_data["returns"] if r["type"] == "Courier Returned" and r["code"] == package_code]
    if rto_returns:
        create_credit_note(invoice.name).save()


def get_return_warehouse(facility_code):
    return frappe.db.get_value("Unicommerce Warehouses", {"unicommerce_facility_code": facility_code}, "return_warehouse")


def create_credit_note(invoice_name):
    credit_note = make_sales_return(invoice_name)
    facility_code = credit_note.get(FACILITY_CODE_FIELD)
    return_warehouse = get_return_warehouse(facility_code)

    for item in credit_note.items:
        item.warehouse = return_warehouse or item.warehouse

    for tax in credit_note.taxes:
        item_wise_tax_detail = json.loads(tax.item_wise_tax_detail)
        for tax_distribution in item_wise_tax_detail.values():
            tax_distribution[1] *= -1
        tax.item_wise_tax_detail = json.dumps(item_wise_tax_detail)

    return credit_note


def check_and_update_customer_initiated_returns(orders, client) -> None:
    """Create a credit note for any customer-initiated return on recently changed orders."""
    for order in _filter_recent_orders(orders):
        so_data = get_sales_order(client, order["code"])
        if so_data:
            sync_customer_initiated_returns(so_data)


def sync_customer_initiated_returns(so_data):
    customer_returns = [r for r in so_data.get("returns", []) if r["type"] == "Customer Returned"]
    for customer_return in customer_returns:
        if not frappe.db.exists("Sales Invoice", {RETURN_CODE_FIELD: customer_return["code"]}):
            create_cir_credit_note(so_data, customer_return)


def create_cir_credit_note(so_data, return_data):
    sales_order_name = frappe.db.get_value("Sales Order", {ORDER_CODE_FIELD: so_data["code"]})
    so = frappe.get_doc("Sales Order", sales_order_name)

    # map SO item -> SI item via the linked child row
    so_item_code_map = {item.get(ORDER_ITEM_CODE_FIELD): item.name for item in so.items}

    invoice_name = frappe.db.get_value("Sales Invoice", {ORDER_CODE_FIELD: so_data["code"], "is_return": 0})
    si = frappe.get_doc("Sales Invoice", invoice_name)
    so_si_item_map = {item.so_detail: item.name for item in si.items}

    credit_note = create_credit_note(si.name)
    credit_note.set(TRACKING_CODE_FIELD, return_data.get("trackingNumber"))
    credit_note.set(SHIPPING_PROVIDER_CODE, return_data.get("shippingProvider"))

    returned_so_codes = [item.get("saleOrderItemCode") for item in return_data.get("returnItems")]
    returned_si_items = [so_si_item_map.get(so_item_code_map.get(code)) for code in returned_so_codes]

    if set(returned_si_items) != set(so_si_item_map.values()):
        _handle_partial_returns(credit_note, returned_si_items)

    credit_note.save()


def _handle_partial_returns(credit_note, returned_items: list[str]) -> None:
    """Drop non-returned items from the credit note and scale down its taxes to match."""
    item_code_to_qty_map = defaultdict(float)
    for item in credit_note.items:
        item_code_to_qty_map[item.item_code] += item.qty

    credit_note.items = [item for item in credit_note.items if item.sales_invoice_item in returned_items]

    returned_qty_map = defaultdict(float)
    for item in credit_note.items:
        returned_qty_map[item.item_code] += item.qty

    for tax in credit_note.taxes:
        item_wise_tax_detail = json.loads(tax.item_wise_tax_detail)
        new_tax_amt = 0.0

        for item_code, tax_distribution in item_wise_tax_detail.items():
            if not tax_distribution[1]:
                continue
            return_percent = returned_qty_map.get(item_code, 0.0) / item_code_to_qty_map.get(item_code)
            tax_distribution[1] *= return_percent
            new_tax_amt += tax_distribution[1]

        tax.tax_amount = new_tax_amt
        tax.item_wise_tax_detail = json.dumps(item_wise_tax_detail)
