# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Unicommerce -> Alaiy OS order sync."""

import json
from collections.abc import Iterator
from typing import Any, NewType

import frappe
from frappe.query_builder.functions import Coalesce
from frappe.utils import flt

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order, search_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    CHANNEL_ID_FIELD, CHANNEL_TAX_ACCOUNT_FIELD_MAP, FACILITY_CODE_FIELD, INVOICE_CODE_FIELD,
    IS_COD_CHECKBOX, ITEM_EXTERNAL_ID_FIELD, ORDER_CODE_FIELD, ORDER_DISPLAY_CODE_FIELD,
    ORDER_ITEM_BATCH_NO, ORDER_ITEM_CODE_FIELD, ORDER_STATUS_FIELD, SETTINGS_DOCTYPE,
    TAX_FIELDS_MAPPING, TAX_RATE_FIELDS_MAPPING,
)
from alaiy_os_connector_unicommerce.unicommerce.customer import sync_customer
from alaiy_os_connector_unicommerce.unicommerce.product.pull import import_product_from_unicommerce
from alaiy_os_connector_unicommerce.unicommerce.utils import (
    get_dummy_tax_category, get_unicommerce_date, need_to_run,
)

UnicommerceOrder = NewType("UnicommerceOrder", dict[str, Any])


def sync_new_orders(client: UnicommerceClient = None, force: bool = False):
    """Called from a scheduled job -- syncs every new order since the last run."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return

    # Also updates last_order_sync as a side effect when it actually runs.
    if not force and not need_to_run(SETTINGS_DOCTYPE, "order_sync_frequency", "last_order_sync"):
        return

    if client is None:
        client = UnicommerceClient()

    status = "COMPLETE" if settings.only_sync_completed_orders else None
    new_orders = _get_new_orders(client, status=status)
    if new_orders is None:
        return

    for order in new_orders:
        sales_order = create_order(order, client=client)
        if sales_order and settings.only_sync_completed_orders:
            _create_sales_invoices(order, sales_order, client)


def _get_new_orders(client: UnicommerceClient, status: str | None) -> Iterator[UnicommerceOrder] | None:
    updated_since = 24 * 60  # minutes
    uni_orders = search_sales_order(client, updated_since=updated_since, status=status)
    if uni_orders is None:
        return

    configured_channels = {
        c.channel_id for c in frappe.get_all("Unicommerce Channel", filters={"enabled": 1}, fields="channel_id")
    }
    # A fresh site has no Unicommerce Channel records at all, and nothing
    # creates them automatically -- without this the loop below silently
    # drops every order as "unconfigured channel" and the sync reports
    # success having imported nothing, with no way to tell why.
    if not configured_channels:
        frappe.log_error(
            title="Unicommerce: no enabled channels configured, order pull imported nothing",
            message=(
                "Order pull fetched orders from Unicommerce but every one was skipped because no "
                "enabled Unicommerce Channel record exists locally. Create one per channel "
                "(channel_id must match Unicommerce's own channel code) and enable it."
            ),
        )
        return

    for order in uni_orders:
        if order["channel"] not in configured_channels:
            continue
        # Re-fetch the full order (search results are summaries) -- if a
        # sales invoice failed to generate for some reason and got skipped,
        # this needs to be re-fetched and retried, not assumed already done.
        full_order = get_sales_order(client, order_code=order["code"])
        if full_order:
            yield full_order


def _create_sales_invoices(unicommerce_order: dict, sales_order, client: UnicommerceClient):
    """Create a Sales Invoice per shipping package -- used only when the
    connector is configured to sync finished orders (only_sync_completed_orders)."""
    from alaiy_os_connector_unicommerce.unicommerce.client.invoicing import get_sales_invoice
    from alaiy_os_connector_unicommerce.unicommerce.fulfillment.invoice import create_sales_invoice

    facility_code = sales_order.get(FACILITY_CODE_FIELD)
    for package in unicommerce_order["shippingPackages"]:
        invoice_data = get_sales_invoice(client, shipping_package_code=package["code"], facility_code=facility_code)
        try:
            existing_si = frappe.db.get_value("Sales Invoice", {INVOICE_CODE_FIELD: invoice_data["invoice"]["code"]})
            if existing_si:
                continue

            warehouse_allocations = _get_warehouse_allocations(sales_order)
            create_sales_invoice(
                invoice_data["invoice"],
                sales_order.name,
                update_stock=1,
                so_data=unicommerce_order,
                warehouse_allocations=warehouse_allocations,
            )
        except Exception:
            frappe.log_error(
                title=f"Unicommerce: failed to create Sales Invoice for {sales_order.name}",
                message=frappe.get_traceback(),
            )


def create_order(payload: UnicommerceOrder, request_id: str | None = None, client=None):
    order = payload

    existing_so = frappe.db.get_value("Sales Order", {ORDER_CODE_FIELD: order["code"]})
    if existing_so:
        so = frappe.get_doc("Sales Order", existing_so)
        # Backfill display order no. on orders synced before the field existed,
        # and propagate it onto invoices/delivery notes already made from it.
        display_order_code = order.get("displayOrderCode")
        if display_order_code and not so.get(ORDER_DISPLAY_CODE_FIELD):
            _backfill_display_order_code(order["code"], display_order_code)
            so.db_set(ORDER_DISPLAY_CODE_FIELD, display_order_code, update_modified=False)
        return so

    if client is None:
        client = UnicommerceClient()

    try:
        _sync_order_items(order, client=client)
        customer = sync_customer(order)
        return _create_order(order, customer)
    except Exception:
        frappe.log_error(
            title=f"Unicommerce: failed to create Sales Order for {order.get('code')}",
            message=frappe.get_traceback(),
        )


def _backfill_display_order_code(uni_order_code: str, display_order_code: str) -> None:
    for doctype in ("Sales Invoice", "Delivery Note"):
        dt = frappe.qb.DocType(doctype)
        (
            frappe.qb.update(dt)
            .set(dt[ORDER_DISPLAY_CODE_FIELD], display_order_code)
            .where(dt[ORDER_CODE_FIELD] == uni_order_code)
            .where(Coalesce(dt[ORDER_DISPLAY_CODE_FIELD], "") == "")
        ).run()


def _sync_order_items(order: UnicommerceOrder, client: UnicommerceClient) -> set:
    """Ensure every item on the order already exists locally, importing any
    that don't."""
    items = {so_item["itemSku"] for so_item in order["saleOrderItems"]}
    for sku in items:
        if not frappe.db.exists("Item", {ITEM_EXTERNAL_ID_FIELD: sku}):
            import_product_from_unicommerce(sku=sku, client=client)
    return items


def _create_order(order: UnicommerceOrder, customer):
    channel_config = frappe.get_doc("Unicommerce Channel", order["channel"])
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)

    is_cancelled = order["status"] == "CANCELLED"
    facility_code = _get_facility_code(order["saleOrderItems"])
    company_address, dispatch_address = settings.get_company_addresses(facility_code)

    so = frappe.get_doc({
        "doctype": "Sales Order",
        "customer": customer.name,
        "naming_series": channel_config.sales_order_series or settings.sales_order_series,
        ORDER_CODE_FIELD: order["code"],
        ORDER_DISPLAY_CODE_FIELD: order.get("displayOrderCode"),
        ORDER_STATUS_FIELD: order["status"],
        CHANNEL_ID_FIELD: order["channel"],
        FACILITY_CODE_FIELD: facility_code,
        IS_COD_CHECKBOX: bool(order["cod"]),
        "transaction_date": get_unicommerce_date(order["displayOrderDateTime"]),
        "delivery_date": get_unicommerce_date(order["fulfillmentTat"]),
        "ignore_pricing_rule": 1,
        "items": _get_line_items(
            order["saleOrderItems"], default_warehouse=channel_config.warehouse, is_cancelled=is_cancelled
        ),
        "company": channel_config.company,
        "taxes": get_taxes(order["saleOrderItems"], channel_config),
        "tax_category": get_dummy_tax_category(),
        "company_address": company_address,
        "dispatch_address_name": dispatch_address,
        "currency": order.get("currencyCode"),
    })

    so.flags.ignore_permissions = True
    so.flags.raw_data = order
    so.insert()
    so.submit()
    if is_cancelled:
        so.cancel()

    return so


def _get_line_items(line_items: list, default_warehouse: str | None = None, is_cancelled: bool = False) -> list:
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    wh_map = settings.get_integration_to_erpnext_wh_mapping(all_wh=True)
    so_items = []

    for item in line_items:
        if not is_cancelled and item.get("statusCode") == "CANCELLED":
            continue

        item_code = frappe.db.get_value("Item", {ITEM_EXTERNAL_ID_FIELD: item["itemSku"]}, "name")
        warehouse = wh_map.get(item["facilityCode"]) or default_warehouse

        so_items.append({
            "item_code": item_code,
            "rate": item["sellingPrice"],
            "qty": 1,
            "stock_uom": "Nos",
            "warehouse": warehouse,
            ORDER_ITEM_CODE_FIELD: item.get("code"),
            ORDER_ITEM_BATCH_NO: _get_batch_no(item),
        })
    return so_items


def get_taxes(line_items: list, channel_config) -> list:
    """
    Tax details are NOT available at the Sales Order stage on Unicommerce
    (different fields, so this won't capture GST here) -- the same function
    is reused at invoice creation, where the real tax detail is present.
    """
    tax_map = {tax_head: 0.0 for tax_head in TAX_FIELDS_MAPPING}
    item_wise_tax_map = {tax_head: {} for tax_head in TAX_FIELDS_MAPPING}
    tax_account_map = {
        tax_head: channel_config.get(account_field)
        for tax_head, account_field in CHANNEL_TAX_ACCOUNT_FIELD_MAP.items()
    }

    for item in line_items:
        item_code = frappe.db.get_value("Item", {ITEM_EXTERNAL_ID_FIELD: item["itemSku"]}, "name")
        for tax_head, uni_field in TAX_FIELDS_MAPPING.items():
            tax_amount = flt(item.get(uni_field)) or 0.0
            tax_rate = item.get(TAX_RATE_FIELDS_MAPPING.get(tax_head, ""), 0.0)
            tax_map[tax_head] += tax_amount
            item_wise_tax_map[tax_head][item_code] = [tax_rate, tax_amount]

    taxes = []
    for tax_head, value in tax_map.items():
        if not value:
            continue
        taxes.append({
            "charge_type": "Actual",
            "account_head": tax_account_map[tax_head],
            "tax_amount": value,
            "description": tax_head.replace("_", " ").upper(),
            "item_wise_tax_detail": json.dumps(item_wise_tax_map[tax_head]),
            "dont_recompute_tax": 1,
        })
    return taxes


def _get_facility_code(line_items: list) -> str:
    facility_codes = {item.get("facilityCode") for item in line_items}
    if len(facility_codes) > 1:
        frappe.throw("Multiple facility codes found in a single order")
    return next(iter(facility_codes))


def _get_batch_no(so_line_item: dict) -> str | None:
    """
    If the vendor batch code on the order line is a valid Batch in Alaiy OS,
    return it. Shape of the source data:
    "batchDTO": {"batchCode": "BA000002", "batchFieldsDTO": {"vendorBatchNumber": "1122", ...}}
    """
    batch_no = ((so_line_item.get("batchDTO") or {}).get("batchFieldsDTO") or {}).get("vendorBatchNumber")
    if batch_no and frappe.db.exists("Batch", batch_no):
        return batch_no


def _get_warehouse_allocations(sales_order) -> list:
    return [
        {
            "sales_order_row": item.name,
            "item_code": item.item_code,
            "warehouse": item.warehouse,
            "batch_no": item.get(ORDER_ITEM_BATCH_NO),
        }
        for item in sales_order.items
    ]
