# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Generate Unicommerce invoices for shipping packages and sync them into ERPNext Sales Invoices."""

import base64
import json
from collections import defaultdict
from typing import Any, NewType

import frappe
import requests
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
from frappe import _
from frappe.utils import cint, flt, nowdate
from frappe.utils.file_manager import save_file

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.invoicing import (
    create_invoice_and_assign_shipper, create_invoice_and_label_by_shipping_code, get_invoice_label,
    get_sales_invoice as get_sales_invoice_data,
)
from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    CHANNEL_ID_FIELD, CUSTOMER_SHIPPING_CHARGE_FIELD, FACILITY_CODE_FIELD, INVOICE_CODE_FIELD,
    IS_COD_CHECKBOX, ITEM_EXTERNAL_ID_FIELD, ITEM_SHIPPING_CHARGE_FIELD, ORDER_CODE_FIELD,
    ORDER_INVOICE_STATUS_FIELD, SETTINGS_DOCTYPE, SHIPPING_METHOD_FIELD,
    SHIPPING_PACKAGE_CODE_FIELD, SHIPPING_PACKAGE_STATUS_FIELD, SHIPPING_PROVIDER_CODE, TRACKING_CODE_FIELD,
)
from alaiy_os_connector_unicommerce.unicommerce.order.pull import get_item_shipping_charge, get_taxes
from alaiy_os_connector_unicommerce.unicommerce.utils import get_unicommerce_date, remove_non_alphanumeric_chars

JsonDict = dict[str, Any]
SOCode = NewType("SOCode", str)
ItemWHAlloc = dict[str, str]
WHAllocation = dict[SOCode, list[ItemWHAlloc]]

INVOICED_STATE = ["PACKED", "READY_TO_SHIP", "DISPATCHED", "MANIFESTED", "SHIPPED", "DELIVERED"]


@frappe.whitelist()
def generate_unicommerce_invoices(sales_orders: list[SOCode], warehouse_allocation: WHAllocation | None = None):
    """Request invoice generation on Unicommerce for the given sales orders, then sync the result.

    warehouse_allocation is only needed if the warehouse changed while shipping or a
    non-group warehouse must be assigned. Shape:
    {"SO0042": [{"item_code": "SKU", "warehouse": "Stores - WP", "sales_order_row": "<so item row name>"}]}
    """
    if isinstance(sales_orders, str):
        sales_orders = json.loads(sales_orders)
    if isinstance(warehouse_allocation, str):
        warehouse_allocation = json.loads(warehouse_allocation)

    if warehouse_allocation:
        _validate_wh_allocation(warehouse_allocation)

    if len(sales_orders) == 1:
        bulk_generate_invoices(sales_orders, warehouse_allocation)
    else:
        frappe.enqueue(
            method=bulk_generate_invoices,
            queue="long",
            timeout=max(1500, len(sales_orders) * 30),
            sales_orders=sales_orders,
            warehouse_allocation=warehouse_allocation,
        )


def bulk_generate_invoices(
    sales_orders: list[SOCode], warehouse_allocation: WHAllocation | None = None, client=None,
):
    if client is None:
        client = UnicommerceClient()

    update_invoicing_status(sales_orders, "Queued")

    failed_orders = []
    for so_code in sales_orders:
        try:
            so = frappe.get_doc("Sales Order", so_code)
            channel = so.get(CHANNEL_ID_FIELD)
            channel_config = frappe.get_cached_doc("Unicommerce Channel", channel)
            wh_allocation = warehouse_allocation.get(so_code) if warehouse_allocation else None
            _generate_invoice(client, so, channel_config, warehouse_allocation=wh_allocation)
        except Exception:
            frappe.log_error(title=f"Unicommerce: failed to generate invoice for {so_code}", message=frappe.get_traceback())
            failed_orders.append(so_code)

    _log_invoice_generation(sales_orders, failed_orders)


def _log_invoice_generation(sales_orders, failed_orders):
    failed_orders = set(failed_orders)
    failed_orders.update(_get_orders_with_missing_invoice(sales_orders))
    successful_orders = list(set(sales_orders) - set(failed_orders))

    update_invoicing_status(list(failed_orders), "Failed")
    update_invoicing_status(successful_orders, "Success")


def _get_orders_with_missing_invoice(sales_orders):
    missing_invoices = set()
    for order in sales_orders:
        uni_so_code = frappe.db.get_value("Sales Order", order, ORDER_CODE_FIELD)
        invoice_exists = frappe.db.exists("Sales Invoice", {ORDER_CODE_FIELD: uni_so_code})
        if not invoice_exists:
            missing_invoices.add(order)
    return missing_invoices


def update_invoicing_status(sales_orders: list[str], status: str) -> None:
    if not sales_orders:
        return
    frappe.db.sql(
        f"""update `tabSales Order` set {ORDER_INVOICE_STATUS_FIELD} = %s where name in %s""",
        (status, sales_orders),
    )


def _validate_wh_allocation(warehouse_allocation: WHAllocation):
    """Validate that provided warehouse allocation is exactly sufficient for fulfilling the orders."""
    if not warehouse_allocation:
        return

    so_codes = list(warehouse_allocation.keys())
    so_item_data = frappe.db.sql(
        """select item_code, sum(qty) as qty, parent as sales_order
            from `tabSales Order Item` where parent in %s group by parent, item_code""",
        (so_codes,), as_dict=True,
    )

    expected_item_qty = {}
    for item in so_item_data:
        expected_item_qty.setdefault(item.sales_order, {})[item.item_code] = item.qty

    for order, item_details in warehouse_allocation.items():
        item_wise_qty = defaultdict(int)
        for item in item_details:
            item_wise_qty[item["item_code"]] += 1

        for item_code, total_qty in item_wise_qty.items():
            expected_qty = expected_item_qty.get(order, {}).get(item_code)
            if abs(total_qty - expected_qty) > 0.1:
                frappe.throw(
                    _("Mismatch in quantity for order {0}, item {1} expected {2} qty, received {3}").format(
                        order, item_code, expected_qty, total_qty
                    )
                )


def _generate_invoice(client: UnicommerceClient, erpnext_order, channel_config, warehouse_allocation=None):
    unicommerce_so_code = erpnext_order.get(ORDER_CODE_FIELD)

    so_data = get_sales_order(client, unicommerce_so_code)
    shipping_packages = [d["code"] for d in so_data["shippingPackages"] if d["status"] == "CREATED"]

    facility_code = erpnext_order.get(FACILITY_CODE_FIELD)

    package_invoice_response_map = {}
    for package in shipping_packages:
        if cint(channel_config.shipping_handled_by_marketplace):
            response = create_invoice_and_label_by_shipping_code(
                client, shipping_package_code=package, facility_code=facility_code
            )
        else:
            response = create_invoice_and_assign_shipper(
                client, shipping_package_code=package, facility_code=facility_code
            )
        package_invoice_response_map[package] = response

    _fetch_and_sync_invoice(
        client,
        unicommerce_so_code,
        erpnext_order.name,
        facility_code,
        warehouse_allocation=warehouse_allocation,
        invoice_responses=package_invoice_response_map,
    )


def _fetch_and_sync_invoice(
    client: UnicommerceClient, unicommerce_so_code, erpnext_so_code, facility_code,
    warehouse_allocation=None, invoice_responses=None,
):
    """Use the invoice generation response to fetch the actual invoice and sync it into ERPNext."""
    so_data = get_sales_order(client, unicommerce_so_code)
    shipping_packages = [d["code"] for d in so_data["shippingPackages"] if d["status"] in INVOICED_STATE]

    for package in shipping_packages:
        invoice_response = invoice_responses.get(package) or {}
        invoice_details = get_sales_invoice_data(client, package, facility_code)
        if not invoice_details or not invoice_details.get("invoice"):
            # get_sales_invoice_data returns None on any failed request --
            # confirmed live, every call was failing with 403 "Forbidden:
            # access resource MINIMAL is needed" (a Unicommerce-side API
            # permission gap on this connector's token, not something fixable
            # here). The blind subscript below crashed with a bare
            # TypeError on every single invoice this order had -- 58,000+
            # occurrences over a week, all originating from the same root
            # cause. Skip this package's invoice sync and let the caller's
            # per-order try/except (bulk_generate_invoices) log and move on,
            # instead of raising an opaque TypeError that gives no hint the
            # real cause is a permission grant, not a code bug.
            frappe.log_error(
                title=f"Unicommerce: could not fetch invoice details for package {package}",
                message=f"unicommerce_so_code={unicommerce_so_code}, facility={facility_code}",
            )
            continue
        invoice_data = invoice_details["invoice"]
        label_pdf = fetch_label_pdf(package, invoice_response, client=client, facility_code=facility_code)
        create_sales_invoice(
            invoice_data,
            erpnext_so_code,
            # See the matching note in order/pull.py -- stock accuracy is a
            # known, separate gap being fixed independently; invoicing and
            # payment status should not be blocked on it.
            update_stock=0,
            shipping_label=label_pdf,
            warehouse_allocations=warehouse_allocation,
            invoice_response=invoice_response,
            so_data=so_data,
        )


def create_sales_invoice(
    si_data: JsonDict, so_code: str, update_stock=0, submit=True, shipping_label=None,
    warehouse_allocations=None, invoice_response=None, so_data: JsonDict | None = None,
):
    """Create an ERPNext Sales Invoice from Unicommerce sales invoice data and its Sales Order."""
    invoice_response = invoice_response or {}
    so_data = so_data or {}
    so = frappe.get_doc("Sales Order", so_code)

    if so_data:
        fully_cancelled = update_cancellation_status(so_data, so)
        if fully_cancelled:
            return

    channel = so.get(CHANNEL_ID_FIELD)
    facility_code = so.get(FACILITY_CODE_FIELD)

    existing_si = frappe.db.get_value("Sales Invoice", {INVOICE_CODE_FIELD: si_data["code"]})
    if existing_si:
        return frappe.get_doc("Sales Invoice", existing_si)

    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    channel_config = frappe.get_cached_doc("Unicommerce Channel", channel)

    uni_line_items = si_data["invoiceItems"]
    warehouse = settings.get_integration_to_erpnext_wh_mapping(all_wh=True).get(facility_code)

    shipping_package_code = si_data.get("shippingPackageCode")
    shipping_package_info = _get_shipping_package(so_data, shipping_package_code) or {}

    tracking_no = invoice_response.get("trackingNumber") or shipping_package_info.get("trackingNumber")
    shipping_provider_code = (
        invoice_response.get("shippingProviderCode")
        or shipping_package_info.get("shippingProvider")
        or shipping_package_info.get("shippingCourier")
    )
    shipping_package_status = shipping_package_info.get("status")

    si = make_sales_invoice(so.name)
    si_line_items = _get_line_items(
        uni_line_items, warehouse, so.name, channel_config.cost_center, warehouse_allocations
    )
    si.set("items", si_line_items)
    si.set("taxes", get_taxes(uni_line_items, channel_config))
    invoice_shipping_charge = sum(flt(row.get(ITEM_SHIPPING_CHARGE_FIELD)) for row in si_line_items)
    si.set(CUSTOMER_SHIPPING_CHARGE_FIELD, invoice_shipping_charge)
    si.set(INVOICE_CODE_FIELD, si_data["code"])
    si.set(SHIPPING_PACKAGE_CODE_FIELD, shipping_package_code)
    si.set(SHIPPING_PROVIDER_CODE, shipping_provider_code)
    si.set(TRACKING_CODE_FIELD, tracking_no)
    si.set(IS_COD_CHECKBOX, so_data.get("cod"))
    si.set(SHIPPING_METHOD_FIELD, shipping_package_info.get("shippingMethod"))
    si.set(SHIPPING_PACKAGE_STATUS_FIELD, shipping_package_status)
    si.set(CHANNEL_ID_FIELD, channel)
    si.set_posting_time = 1
    si.posting_date = get_unicommerce_date(si_data["created"])
    si.transaction_date = si.posting_date
    si.naming_series = channel_config.sales_invoice_series or settings.sales_invoice_series
    si.delivery_date = so.delivery_date
    si.ignore_pricing_rule = 1
    si.update_stock = False if settings.delivery_note else update_stock
    si.flags.ignore_permissions = True
    si.insert()

    if invoice_shipping_charge:
        _backfill_shipping_charge_to_order(so, si_line_items)

    _verify_total(si, si_data)

    attach_unicommerce_docs(
        sales_invoice=si.name,
        invoice=si_data.get("encodedInvoice"),
        label=shipping_label,
        invoice_code=si_data["code"],
        package_code=si_data.get("shippingPackageCode"),
    )

    item_warehouses = {d.warehouse for d in si.items}
    for wh in item_warehouses:
        if update_stock and cint(frappe.db.get_value("Warehouse", wh, "is_group")):
            # can't submit a stock transaction where the warehouse is a group
            return si

    if submit:
        si.submit()
        # Commit right away -- confirmed live that a make_payment_entry
        # failure immediately after submit() (e.g. its own "already fully
        # paid" false-positive on freshly-submitted data) rolled back this
        # invoice's own GL Entries along with it, leaving a submitted
        # (docstatus=1) Sales Invoice with zero accounting entries. The
        # invoice succeeding must never be undone by a payment step failing.
        frappe.db.commit()

    try:
        make_payment_entry(si, channel_config, si.posting_date)
    except Exception:
        frappe.log_error(
            title=f"Unicommerce: failed to create Payment Entry for {si.name}",
            message=frappe.get_traceback(),
        )

    return si


def attach_unicommerce_docs(
    sales_invoice: str, invoice: str | None, label: str | None, invoice_code: str | None, package_code: str | None,
) -> None:
    """Attach the base64-encoded invoice and label PDFs to the given Sales Invoice."""
    invoice_code = remove_non_alphanumeric_chars(invoice_code)
    package_code = remove_non_alphanumeric_chars(package_code)

    if invoice:
        save_file(f"unicommerce-invoice-{invoice_code}.pdf", invoice, "Sales Invoice", sales_invoice, decode=True, is_private=1)
    if label:
        save_file(f"unicommerce-label-{package_code}.pdf", label, "Sales Invoice", sales_invoice, decode=True, is_private=1)


def _get_line_items(
    line_items, warehouse: str, so_code: str, cost_center: str, warehouse_allocations: WHAllocation | None = None,
) -> list[dict[str, Any]]:
    """Invoice items can differ from and are consolidated across order items, so recompute here."""
    si_items = []
    for item in line_items:
        item_code = frappe.db.get_value("Item", {ITEM_EXTERNAL_ID_FIELD: item["itemSku"]}, "name")
        qty = cint(item["quantity"]) or 1
        # This one Unicommerce line explodes into `qty` rows of 1 each below
        # -- split its shipping charge evenly across them so summing the
        # exploded rows back up reconstructs the original line's charge,
        # rather than multiplying it by qty.
        shipping_charge_per_row = get_item_shipping_charge(item) / qty
        for __ in range(qty):
            si_items.append({
                "item_code": item_code,
                "rate": item["unitPrice"],  # discount already removed from this price
                "qty": 1,
                "stock_uom": "Nos",
                "warehouse": warehouse,
                "cost_center": cost_center,
                "sales_order": so_code,
                ITEM_SHIPPING_CHARGE_FIELD: shipping_charge_per_row,
            })

    if warehouse_allocations:
        return _assign_wh_and_so_row(si_items, warehouse_allocations, so_code)
    return si_items


def _assign_wh_and_so_row(line_items, warehouse_allocation: list[ItemWHAlloc], so_code: str):
    so_items = frappe.get_doc("Sales Order", so_code).items
    so_item_price_map = {d.name: d.rate for d in so_items}

    warehouse_allocation = [d for d in warehouse_allocation if d["sales_order_row"] in so_item_price_map]
    for item in warehouse_allocation:
        item["rate"] = so_item_price_map.get(item["sales_order_row"])

    sort_key = lambda d: (d.get("item_code"), d.get("rate"))  # noqa
    warehouse_allocation.sort(key=sort_key)
    line_items.sort(key=sort_key)

    for item, wh_alloc in zip(line_items, warehouse_allocation, strict=False):
        item["so_detail"] = wh_alloc["sales_order_row"]
        item["warehouse"] = wh_alloc["warehouse"]
        item["batch_no"] = wh_alloc.get("batch_no")

    return line_items


def _backfill_shipping_charge_to_order(so, si_line_items: list) -> None:
    """Shipping charge is only ever known at invoice time (see
    get_item_shipping_charge's docstring) -- push it back onto the Sales
    Order/Sales Order Item it originated from, same shape as
    _backfill_display_order_code. Additive, not overwritten: an order
    shipped across multiple packages/invoices gets more than one of these
    calls, each covering only its own slice.
    """
    current = flt(frappe.db.get_value("Sales Order", so.name, CUSTOMER_SHIPPING_CHARGE_FIELD))
    added = sum(flt(row.get(ITEM_SHIPPING_CHARGE_FIELD)) for row in si_line_items)
    frappe.db.set_value("Sales Order", so.name, CUSTOMER_SHIPPING_CHARGE_FIELD, current + added, update_modified=False)

    charge_by_item = {}
    for row in si_line_items:
        charge_by_item[row["item_code"]] = charge_by_item.get(row["item_code"], 0) + flt(row.get(ITEM_SHIPPING_CHARGE_FIELD))

    for so_item in frappe.get_all("Sales Order Item", filters={"parent": so.name}, fields=["name", "item_code", ITEM_SHIPPING_CHARGE_FIELD]):
        added_for_item = charge_by_item.get(so_item.item_code)
        if not added_for_item:
            continue
        current_item = flt(so_item.get(ITEM_SHIPPING_CHARGE_FIELD))
        frappe.db.set_value(
            "Sales Order Item", so_item.name, ITEM_SHIPPING_CHARGE_FIELD, current_item + added_for_item,
            update_modified=False,
        )

    _validate_shipping_charge_total(so.name)


def _validate_shipping_charge_total(so_name: str) -> None:
    """Same shape as _verify_total: leave a comment rather than raise if
    SUM(order_items.shipping_charge) drifts from the order-level total --
    the two are written in separate statements above (one order-level
    increment, one per-item), so a partial failure between them is
    detectable without failing the whole invoice."""
    order_total = flt(frappe.db.get_value("Sales Order", so_name, CUSTOMER_SHIPPING_CHARGE_FIELD))
    item_sum = flt(frappe.db.sql(
        f"""SELECT COALESCE(SUM({ITEM_SHIPPING_CHARGE_FIELD}), 0) FROM `tabSales Order Item` WHERE parent = %s""",
        so_name,
    )[0][0])
    if abs(order_total - item_sum) > 0.5:
        frappe.get_doc("Sales Order", so_name).add_comment(
            text=f"Shipping charge mismatch: order-level {order_total} vs item-level sum {item_sum}")


def _verify_total(si, si_data) -> None:
    """Leave a comment if the grand total does not match the Unicommerce total."""
    if abs(si.grand_total - flt(si_data["total"])) > 0.5:
        si.add_comment(text=f"Invoice totals mismatch: Unicommerce reported total of {si_data['total']}")


def _get_shipping_package(si_data, package_code):
    if not package_code:
        return
    for package in si_data.get("shippingPackages") or []:
        if package.get("code") == package_code:
            return package


def make_payment_entry(invoice, channel_config, invoice_posting_date=None):
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    payment_entry = get_payment_entry(invoice.doctype, invoice.name, bank_account=channel_config.cash_or_bank_account)
    payment_entry.reference_no = invoice.get(ORDER_CODE_FIELD) or invoice.name
    payment_entry.posting_date = invoice_posting_date or nowdate()
    payment_entry.reference_date = invoice_posting_date or nowdate()

    payment_entry.insert(ignore_permissions=True)
    payment_entry.submit()


def fetch_label_pdf(package, invoicing_response, client, facility_code):
    """createInvoiceAndGenerateLabel already returns the label as a base64
    string directly (`label`) -- use that first and skip a redundant
    download. Only fall back to fetching the link (older/marketplace-shipped
    responses that don't carry `label`) or a fresh API call if neither is
    present."""
    invoicing_response = invoicing_response or {}
    if invoicing_response.get("label"):
        return invoicing_response["label"]
    if invoicing_response.get("shippingLabelLink"):
        return fetch_pdf_as_base64(invoicing_response["shippingLabelLink"])
    return get_invoice_label(client, package, facility_code)


def fetch_pdf_as_base64(link):
    try:
        response = requests.get(link)
        response.raise_for_status()
        return base64.b64encode(response.content)
    except Exception:
        return


def update_cancellation_status(so_data, so) -> bool:
    """Check and update cancellation status; return True if the order was fully cancelled."""
    if so_data.get("status") == "CANCELLED":
        so.cancel()
        return True

    from alaiy_os_connector_unicommerce.unicommerce.order.cancellation import update_erpnext_order_items

    update_erpnext_order_items(so_data, so)
    return False


def on_submit(self, method=None):
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return

    sales_order = self.get("items")[0].sales_order
    unicommerce_order_code = frappe.db.get_value("Sales Order", sales_order, ORDER_CODE_FIELD)
    if not unicommerce_order_code:
        return

    attached_docs = frappe.get_all(
        "File", fields=["file_name", "file_url"],
        filters={"attached_to_name": self.name, "file_name": ("like", "unicommerce%")},
        order_by="file_name",
    )
    pick_list_rows = frappe.get_all(
        "Pick List Unicommerce Order Detail", fields=["name", "parent"],
        filters=[{"sales_order": sales_order, "docstatus": 0}],
    )
    for row in pick_list_rows:
        if not row.parent or not frappe.db.exists("Pick List", row.parent):
            continue
        if attached_docs:
            frappe.db.set_value(
                "Pick List Unicommerce Order Detail", row.name,
                {"sales_invoice": self.name, "invoice_url": attached_docs[0].file_name, "invoice_pdf": attached_docs[0].file_url},
            )
        else:
            frappe.db.set_value("Pick List Unicommerce Order Detail", row.name, {"sales_invoice": self.name})


def on_cancel(self, method=None):
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return

    results = frappe.db.get_all("Pick List Unicommerce Order Detail", filters={"sales_invoice": self.name, "docstatus": 1})
    if results:
        ignored_doctypes = list(self.get("ignore_linked_doctypes", []))
        ignored_doctypes.append("Pick List")
        self.ignore_linked_doctypes = ignored_doctypes
