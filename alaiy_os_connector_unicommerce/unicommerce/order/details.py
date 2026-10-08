# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Order, line and shipment details from the sale order payload that have no
native ERPNext field: customer GSTIN, payment details, discounts and vouchers,
holds, cancellation reasons and shipment extras.

Each group is a table of (fieldname, label, fieldtype, extractor). The same
table creates the custom fields, builds the values when an order is imported
and refreshes them on an existing order, so a field cannot exist without being
filled or the other way round."""

import json

import frappe
from frappe.utils import flt, now_datetime

from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ITEM_SHIPPING_CHARGE_FIELD,
    ORDER_ITEM_CODE_FIELD,
    SHIPPING_PACKAGE_STATUS_FIELD,
    TRACKING_LINK_FIELD,
)
from alaiy_os_connector_unicommerce.unicommerce.utils import get_unicommerce_datetime

DETAILS_SYNCED_FIELD = "unicommerce_details_synced_at"
#: When the background fill last tried this order, successful or not, so an order Unicommerce cannot
#: return is retried daily instead of blocking the front of the queue every hour.
DETAILS_ATTEMPTED_FIELD = "unicommerce_details_attempted_at"


def _join(values):
    return ", ".join(dict.fromkeys(str(v) for v in values if v)) or None


def _json(value):
    return json.dumps(value) if value else None


def _payments(order):
    return order.get("paymentDetail") or []


def _cancelled_lines(order):
    reasons = [
        f"{item.get('itemSku')}: {item.get('cancellationReason') or 'no reason given'}"
        for item in order.get("saleOrderItems") or []
        if item.get("statusCode") == "CANCELLED"
    ]
    return "\n".join(dict.fromkeys(reasons)) or None


def _item_details(item):
    # The payload carries both names; whichever one is filled holds the rows.
    rows = item.get("itemDetailFields") or item.get("itemDetailFieldDTOList") or []
    parts = [
        f"{key}: {value}"
        for row in rows
        for key, value in (row or {}).items()
        if value
    ]
    return "; ".join(parts) or None


#: (fieldname, label, fieldtype, value from the sale order)
ORDER_FIELDS = [
    ("unicommerce_customer_gstin", "Customer GSTIN", "Data", lambda o: o.get("customerGSTIN")),
    ("unicommerce_notification_email", "Notification Email", "Data", lambda o: o.get("notificationEmail")),
    ("unicommerce_notification_mobile", "Notification Mobile", "Data", lambda o: o.get("notificationMobile")),
    ("unicommerce_order_category", "Order Category", "Data", lambda o: o.get("orderCategory")),
    ("unicommerce_order_source", "Order Source", "Data", lambda o: o.get("source")),
    ("unicommerce_channel_processing_time", "Channel Processing Time", "Datetime",
     lambda o: get_unicommerce_datetime(o.get("channelProcessingTime"))),
    ("unicommerce_priority", "Fulfilment Priority", "Int", lambda o: o.get("priority")),
    ("unicommerce_additional_info", "Additional Info", "Small Text", lambda o: o.get("additionalInfo")),
    ("unicommerce_custom_values", "Custom Field Values", "Small Text", lambda o: _json(o.get("customFieldValues"))),
    ("unicommerce_payment_mode", "Payment Mode", "Data", lambda o: _join(p.get("paymentMode") for p in _payments(o))),
    ("unicommerce_payment_transactions", "Payment Transaction IDs", "Small Text",
     lambda o: _join(p.get("transactionId") for p in _payments(o))),
    ("unicommerce_amount_paid", "Amount Paid", "Currency",
     lambda o: sum(flt(p.get("amountPaid")) for p in _payments(o)) if _payments(o) else None),
    ("unicommerce_total_discount", "Total Discount", "Currency", lambda o: o.get("totalDiscount")),
    ("unicommerce_on_hold", "On Hold", "Check",
     lambda o: int(any(i.get("onHold") for i in o.get("saleOrderItems") or []))),
    ("unicommerce_cancelled_lines", "Cancelled Lines and Reasons", "Small Text", _cancelled_lines),
    # Set whenever the full payload has been applied; the background fill picks orders where it is empty.
    (DETAILS_SYNCED_FIELD, "Details Synced At", "Datetime", lambda o: now_datetime()),
]

#: Per sale order line (Sales Order Item).
ITEM_FIELDS = [
    ("unicommerce_line_mrp", "Max Retail Price", "Currency", lambda i: i.get("maxRetailPrice")),
    ("unicommerce_line_price_before_tax_discount", "Price Before Tax and Discount", "Currency",
     lambda i: i.get("sellingPriceWithoutTaxesAndDiscount")),
    ("unicommerce_line_discount", "Discount", "Currency", lambda i: i.get("discount")),
    ("unicommerce_line_tcs", "TCS", "Currency", lambda i: i.get("tcs")),
    ("unicommerce_line_voucher_code", "Voucher Code", "Data", lambda i: i.get("voucherCode")),
    ("unicommerce_line_voucher_value", "Voucher Value", "Currency", lambda i: i.get("voucherValue")),
    ("unicommerce_line_store_credit", "Store Credit", "Currency", lambda i: i.get("storeCredit")),
    ("unicommerce_line_prepaid_amount", "Prepaid Amount", "Currency", lambda i: i.get("prepaidAmount")),
    ("unicommerce_line_cod_charges", "COD Charges", "Currency", lambda i: i.get("cashOnDeliveryCharges")),
    ("unicommerce_line_gift_wrap", "Gift Wrap", "Check", lambda i: int(bool(i.get("giftWrap")))),
    ("unicommerce_line_gift_message", "Gift Message", "Small Text", lambda i: i.get("giftMessage")),
    ("unicommerce_line_on_hold", "On Hold", "Check", lambda i: int(bool(i.get("onHold")))),
    ("unicommerce_line_packet_number", "Parcels", "Int", lambda i: i.get("packetNumber")),
    ("unicommerce_line_replacement_order", "Replacement Order", "Data", lambda i: i.get("replacementSaleOrderCode")),
    ("unicommerce_line_bundle_sku", "Bundle SKU", "Data", lambda i: i.get("bundleSkuCode")),
    ("unicommerce_line_item_details", "Serial / IMEI / Seal", "Small Text", _item_details),
]

#: Per shipping package, written to the Sales Order (furthest package) and to the Sales Invoice of that package.
PACKAGE_FIELDS = [
    ("unicommerce_tracking_status", "Tracking Status", "Data", lambda p: p.get("trackingStatus")),
    ("unicommerce_courier_status", "Courier Status", "Data", lambda p: p.get("courierStatus")),
    ("unicommerce_dispatched_on", "Dispatched On", "Datetime", lambda p: get_unicommerce_datetime(p.get("dispatched"))),
    ("unicommerce_estimated_weight", "Estimated Weight (g)", "Float", lambda p: p.get("estimatedWeight")),
    ("unicommerce_actual_weight", "Actual Weight (g)", "Float", lambda p: p.get("actualWeight")),
    ("unicommerce_collectable_amount", "Amount To Collect", "Currency", lambda p: p.get("collectableAmount")),
    ("unicommerce_collected_amount", "Amount Collected", "Currency", lambda p: p.get("collectedAmount")),
    ("unicommerce_payment_reconciled", "Payment Reconciled", "Check", lambda p: int(bool(p.get("paymentReconciled")))),
    ("unicommerce_pod_code", "Proof of Delivery Code", "Data", lambda p: p.get("podCode")),
    ("unicommerce_manifest_code", "Shipping Manifest", "Data", lambda p: p.get("shippingManifestCode")),
    ("unicommerce_irn", "E-Invoice IRN", "Data", lambda p: p.get("irn")),
    ("unicommerce_invoice_date", "Invoice Date", "Datetime", lambda p: get_unicommerce_datetime(p.get("invoiceDate"))),
]


def _values(table, source):
    return {name: value for name, _l, _t, get in table if (value := get(source)) not in (None, "")}


def order_values(order):
    return _values(ORDER_FIELDS, order)


def item_values(item):
    return _values(ITEM_FIELDS, item)


def package_values(package):
    return _values(PACKAGE_FIELDS, package)


def _definitions(table, after, section_label=None):
    defs = []
    if section_label:
        section = f"{after}_section"
        defs.append(dict(fieldname=section, label=section_label, fieldtype="Section Break",
                         collapsible=1, insert_after=after))
        after = section
    for name, label, fieldtype, _get in table:
        defs.append(dict(fieldname=name, label=label, fieldtype=fieldtype, insert_after=after, read_only=1))
        after = name
    return defs


def custom_field_defs():
    """Custom Field definitions for setup/install.py, keyed by doctype."""
    attempted = dict(fieldname=DETAILS_ATTEMPTED_FIELD, label="Details Last Attempted At", fieldtype="Datetime",
                     insert_after=DETAILS_SYNCED_FIELD, read_only=1, hidden=1)
    return {
        "Sales Order": (
            _definitions(ORDER_FIELDS, TRACKING_LINK_FIELD, "Unicommerce Order Details")
            + _definitions(PACKAGE_FIELDS, ORDER_FIELDS[-1][0], "Unicommerce Shipment Details")
            + [attempted]
        ),
        "Sales Order Item": _definitions(ITEM_FIELDS, ITEM_SHIPPING_CHARGE_FIELD),
        "Sales Invoice": _definitions(PACKAGE_FIELDS, SHIPPING_PACKAGE_STATUS_FIELD),
    }


def apply_order_details(so_name, order):
    """Refresh the order-level and line-level details of an existing Sales
    Order from a full sale order payload (holds clear, payments reconcile)."""
    values = order_values(order)
    if values:
        frappe.db.set_value("Sales Order", so_name, values)

    rows = frappe.db.get_values(
        "Sales Order Item", {"parent": so_name}, fieldname=["name", ORDER_ITEM_CODE_FIELD], as_dict=True
    )
    row_by_code = {row[ORDER_ITEM_CODE_FIELD]: row["name"] for row in rows if row.get(ORDER_ITEM_CODE_FIELD)}
    for item in order.get("saleOrderItems") or []:
        row = row_by_code.get(item.get("code"))
        values = item_values(item) if row else None
        if values:
            frappe.db.set_value("Sales Order Item", row, values)


_PERSONAL = {
    "name", "addressLine1", "addressLine2", "phone", "email", "notificationEmail", "notificationMobile",
    "customer", "customerGSTIN", "billingAddress", "addresses",
}


def _flatten(value, path="", out=None):
    out = {} if out is None else out
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in _PERSONAL:
                out[f"{path}.{key}" if path else key] = "<personal data, masked>"
            else:
                _flatten(inner, f"{path}.{key}" if path else key, out)
    elif isinstance(value, list):
        out[f"{path}[]"] = f"{len(value)} item(s)"
        if value:
            _flatten(value[0], f"{path}[0]", out)
    else:
        out[path] = value
    return out


def audit_order(order_code=None):
    """Read-only. Fetches one sale order from Unicommerce and prints every
    field it returns (personal data masked), then what this connector stored
    for the same order, so the two can be compared side by side.

    bench --site <site> execute alaiy_os_connector_unicommerce.unicommerce.order.details.audit_order
    bench --site <site> execute ...audit_order --kwargs "{'order_code': 'SO123'}"
    """
    from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
    from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
    from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD

    if not order_code:
        order_code = frappe.db.get_value(
            "Sales Order", {ORDER_CODE_FIELD: ("is", "set"), "docstatus": 1}, ORDER_CODE_FIELD, order_by="creation desc"
        )
    so_data = get_sales_order(UnicommerceClient(), order_code)
    if not so_data:
        print(f"No data returned for {order_code} (check the API user's access).")
        return

    print(f"=== Unicommerce returned for {order_code} ===")
    for path, value in _flatten(so_data).items():
        print(f"{path} = {value}")

    so_name = frappe.db.get_value("Sales Order", {ORDER_CODE_FIELD: order_code})
    if not so_name:
        return
    print(f"\n=== Stored on Sales Order {so_name} (unicommerce_* fields with a value) ===")
    for key, value in frappe.get_doc("Sales Order", so_name).as_dict().items():
        if key.startswith("unicommerce_") and value not in (None, "", 0):
            print(f"{key} = {'<masked>' if 'email' in key or 'mobile' in key or 'gstin' in key else value}")
