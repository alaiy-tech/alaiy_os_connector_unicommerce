# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Sync order cancellations and customer/RTO returns from Unicommerce into ERPNext."""

import json
from collections import defaultdict
from datetime import date, datetime

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from erpnext.controllers.accounts_controller import update_child_qty_rate

from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_return, get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    CHANNEL_ID_FIELD, FACILITY_CODE_FIELD, ITEM_EXTERNAL_ID_FIELD, ORDER_CODE_FIELD,
    ORDER_ITEM_CODE_FIELD, ORDER_STATUS_FIELD,
    RETURN_CODE_FIELD, RETURN_COURIER_FIELD, RETURN_PINCODE_FIELD, RETURN_REASON_FIELD,
    RETURN_TYPE_FIELD, ITEM_RETURN_REASON_FIELD, ITEM_RETURN_QC_FIELD,
    SHIPPING_PACKAGE_CODE_FIELD, SHIPPING_PROVIDER_CODE, TRACKING_CODE_FIELD,
)


def _ensure_return_details(invoice_name, client, package_code=None, reverse_pickup_code=None,
                           return_type=None):
    """Fill the return-detail fields on a credit note that is missing them.

    Complements apply_return_details, which only ever runs while a credit note
    is being built. A note created before these fields existed -- or on a run
    where the detail fetch returned nothing -- would otherwise stay blank for
    good, since every caller skips a package that already has a credit note.

    Writes columns directly: these are read-only reporting fields on a
    submitted document, and cancel/amend to set a return reason would be far
    worse than the write itself.
    """
    current = frappe.db.get_value(
        "Sales Invoice", invoice_name,
        [RETURN_TYPE_FIELD, RETURN_REASON_FIELD, FACILITY_CODE_FIELD], as_dict=True,
    )
    if not current or (current.get(RETURN_TYPE_FIELD) and current.get(RETURN_REASON_FIELD)):
        return

    values = {}
    if return_type and not current.get(RETURN_TYPE_FIELD):
        values[RETURN_TYPE_FIELD] = return_type

    facility_code = current.get(FACILITY_CODE_FIELD)
    if facility_code and not current.get(RETURN_REASON_FIELD):
        try:
            detail = get_return(client, facility_code, shipment_code=package_code,
                                reverse_pickup_code=reverse_pickup_code)
        except Exception:
            detail = None
        if detail:
            reason, courier, pincode = _parse_return_detail(detail)
            if reason:
                values[RETURN_REASON_FIELD] = reason
            if courier:
                values[RETURN_COURIER_FIELD] = courier
            if pincode:
                values[RETURN_PINCODE_FIELD] = pincode
            _heal_item_return_reasons(invoice_name, detail)

    if values:
        frappe.db.set_value("Sales Invoice", invoice_name, values, update_modified=False)


def _heal_item_return_reasons(invoice_name, detail):
    """Fill the per-SKU return fields on an existing credit note's item rows.

    apply_return_details sets these while the document is being built, which
    only ever reaches notes created after the fields existed. The document-level
    reason is right for a single-SKU return -- 94% of them -- but a multi-SKU
    return keeps only the first item's reason at that level, so the rest are
    only recoverable per row.

    Writes columns directly, same reasoning as the caller: these are read-only
    reporting fields on a submitted document, and a cancel/amend cycle to set a
    return reason would be far worse than the write.
    """
    by_sku = _return_reason_by_sku(detail)
    if not by_sku:
        return
    rows = frappe.db.get_all(
        "Sales Invoice Item", filters={"parent": invoice_name},
        fields=["name", "item_code", ITEM_RETURN_REASON_FIELD],
    )
    for row in rows:
        if row.get(ITEM_RETURN_REASON_FIELD):
            continue
        external = frappe.db.get_value("Item", row["item_code"], ITEM_EXTERNAL_ID_FIELD)
        reason, qc = by_sku.get(external) or by_sku.get(row["item_code"]) or (None, None)
        values = {}
        if reason:
            values[ITEM_RETURN_REASON_FIELD] = reason
        if qc:
            values[ITEM_RETURN_QC_FIELD] = qc
        if values:
            frappe.db.set_value("Sales Invoice Item", row["name"], values,
                                update_modified=False)


def _return_reason_by_sku(detail):
    """{skuCode: (reason, qc_comment)} from an /oms/return/get payload.

    returnSaleOrderItems is a LIST, one entry per returned SKU, and a customer
    returning three items can give a different reason for each. The
    document-level field on the credit note can only hold one of them, so the
    rest are kept here against their own invoice item rows.
    """
    items = detail.get("returnSaleOrderItems") or []
    if isinstance(items, dict):
        items = [items]
    by_sku = {}
    for item in items:
        sku = (item.get("skuCode") or "").strip()
        if not sku:
            continue
        reason = (item.get("marketplaceReturnReason") or item.get("returnRemarks")
                  or item.get("trackingStatus") or item.get("courierStatus"))
        by_sku[sku] = (reason, item.get("putawayQcComment"))
    return by_sku


def _apply_item_return_reasons(credit_note, detail):
    """Stamp each returned SKU's own reason onto its invoice item row."""
    by_sku = _return_reason_by_sku(detail)
    if not by_sku:
        return
    for row in (credit_note.items or []):
        # The Unicommerce SKU is the Item's external id, not necessarily the
        # ERPNext item_code -- match on whichever the payload used.
        external = frappe.db.get_value("Item", row.item_code, ITEM_EXTERNAL_ID_FIELD)
        reason, qc = by_sku.get(external) or by_sku.get(row.item_code) or (None, None)
        if reason:
            row.set(ITEM_RETURN_REASON_FIELD, reason)
        if qc:
            row.set(ITEM_RETURN_QC_FIELD, qc)


def _parse_return_detail(detail):
    """Pull reason, courier and pincode out of an /oms/return/get payload."""
    # returnSaleOrderValue is a list of one per shipment in practice, but the
    # docs type it as a list -- take the first rather than assuming a dict.
    values = detail.get("returnSaleOrderValue") or []
    value = values[0] if isinstance(values, list) and values else (values if isinstance(values, dict) else {})

    items = detail.get("returnSaleOrderItems") or []
    item = items[0] if isinstance(items, list) and items else (items if isinstance(items, dict) else {})

    # Confirmed against live Flipkart RTO data: rtoReason,
    # marketplaceReturnReason and returnRemarks are all null on a real RTO --
    # the only signal of WHY it came back is the courier/tracking status
    # ("COURIER_RETURN-DELIVERED", "RTO_DELIVERED_TO_SELLER"). Fall through to
    # those rather than storing an empty reason, and keep the explicit reason
    # fields first for the marketplaces that do populate them.
    reason = (
        value.get("rtoReason")
        or item.get("marketplaceReturnReason")
        or item.get("returnRemarks")
        or item.get("trackingStatus")
        or item.get("courierStatus")
    )

    # Same story for the courier: both name fields are null live, while the
    # shipping provider code carries the real carrier ("E-Kart Logistics").
    courier = (
        value.get("rtoCourierName")
        or value.get("courierName")
        or value.get("rtoShippingProviderCode")
        or value.get("shippingProviderCode")
    )

    # Where it came back from. Live payloads carry SHIPPING/BILLING and often
    # no PICKUP row at all, so prefer PICKUP, then SHIPPING, then whatever is
    # first -- BILLING is the customer's billing address and is the least
    # meaningful for return-origin analysis.
    addresses = detail.get("returnAddressDetailsList") or []
    pickup = (
        next((a for a in addresses if a.get("type") == "PICKUP"), None)
        or next((a for a in addresses if a.get("type") == "SHIPPING"), None)
        or (addresses[0] if addresses else {})
    )
    return reason, courier, pickup.get("pincode")


def apply_return_details(credit_note, client, facility_code, return_type,
                         shipment_code=None, reverse_pickup_code=None):
    """Stamp why this came back onto the credit note.

    Best-effort by design: the credit note is the real accounting document and
    must not fail to save because a reporting detail could not be fetched --
    /oms/return/get is a separate access resource, so a site can be entitled
    to returns without being entitled to this. Sets the type either way, since
    that is known from the caller without an API call.
    """
    credit_note.set(RETURN_TYPE_FIELD, return_type)

    if not facility_code or not (shipment_code or reverse_pickup_code):
        return
    try:
        detail = get_return(client, facility_code, shipment_code=shipment_code,
                            reverse_pickup_code=reverse_pickup_code)
    except Exception:
        return
    if not detail:
        return

    _apply_item_return_reasons(credit_note, detail)

    reason, courier, pincode = _parse_return_detail(detail)
    if reason:
        credit_note.set(RETURN_REASON_FIELD, reason)
    if courier:
        credit_note.set(RETURN_COURIER_FIELD, courier)
    if pincode:
        credit_note.set(RETURN_PINCODE_FIELD, pincode)


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
    """Create and submit a credit note when a package is expected to be returned to origin."""
    package_code = package_info["code"]

    invoice = frappe.db.get_value(
        "Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: package_code},
        ["name", ORDER_CODE_FIELD, CHANNEL_ID_FIELD], as_dict=True,
    )
    if not invoice:
        # Package is on its way back but was never invoiced locally (order's
        # invoice generation was skipped/delayed) -- nothing to attach a
        # credit note to. Log rather than silently drop: this return is
        # otherwise invisible until someone backfills the missing invoice.
        frappe.log_error(
            title="Unicommerce: RTO package has no local Sales Invoice",
            message=f"Shipping package {package_code} is returning to origin but no Sales Invoice "
                    f"carries this shipping package code -- its order was likely never invoiced.",
        )
        return

    already_returned = frappe.db.get_value("Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: package_code, "is_return": 1})
    if already_returned:
        # The credit note exists, but it predates the return-detail fields (or
        # was created on a run where the detail fetch came back empty). Fill it
        # in here rather than leaving it blank forever: this sweep already
        # revisits every package in a return state, so history heals itself on
        # the normal schedule instead of needing a one-off backfill.
        _ensure_return_details(already_returned, client, package_code=package_code, return_type="RTO")
        return

    so_data = get_sales_order(client, invoice.get(ORDER_CODE_FIELD))
    rto_returns = [r for r in so_data["returns"] if r["type"] == "Courier Returned" and r["code"] == package_code]
    if rto_returns:
        credit_note = create_credit_note(invoice.name)
        apply_return_details(
            credit_note, client, credit_note.get(FACILITY_CODE_FIELD), "RTO",
            shipment_code=package_code,
        )
        credit_note.save()
        credit_note.submit()


def get_return_warehouse(facility_code):
    return frappe.db.get_value("Unicommerce Warehouses", {"unicommerce_facility_code": facility_code}, "return_warehouse")


def create_credit_note(invoice_name):
    credit_note = make_sales_return(invoice_name)
    facility_code = credit_note.get(FACILITY_CODE_FIELD)
    return_warehouse = get_return_warehouse(facility_code)

    for item in credit_note.items:
        item.warehouse = return_warehouse or item.warehouse

    for tax in credit_note.taxes:
        # Confirmed live: this field does not exist as an attribute on
        # Sales Taxes and Charges on this site's ERPNext version at all
        # (AttributeError, not an empty/None value) -- 290 real credit
        # notes failed on this single line before it was guarded. The
        # negation here was only correcting a stale item-wise breakdown
        # left over from the original invoice; skipping it degrades to
        # make_sales_return's own tax totals, which are already correct,
        # rather than blocking every credit note over a detail field
        # this version doesn't carry.
        if not hasattr(tax, "item_wise_tax_detail") or not tax.item_wise_tax_detail:
            continue
        item_wise_tax_detail = json.loads(tax.item_wise_tax_detail)
        for tax_distribution in item_wise_tax_detail.values():
            tax_distribution[1] *= -1
        tax.item_wise_tax_detail = json.dumps(item_wise_tax_detail)
        tax.item_wise_tax_detail = json.dumps(item_wise_tax_detail)

    return credit_note


def check_and_update_customer_initiated_returns(orders, client) -> None:
    """Create a credit note for any customer-initiated return on recently changed orders."""
    for order in _filter_recent_orders(orders):
        try:
            so_data = get_sales_order(client, order["code"])
            if so_data:
                sync_customer_initiated_returns(so_data, client=client)
        except Exception:
            frappe.log_error(
                title=f"Unicommerce: customer-initiated return sync failed for order {order.get('code')}",
                message=frappe.get_traceback(),
            )
            continue


def sync_customer_initiated_returns(so_data, client=None):
    customer_returns = [r for r in so_data.get("returns", []) if r["type"] == "Customer Returned"]
    for customer_return in customer_returns:
        existing = frappe.db.get_value("Sales Invoice", {RETURN_CODE_FIELD: customer_return["code"]})
        if not existing:
            create_cir_credit_note(so_data, customer_return, client=client)
        elif client:
            # Same self-heal as the RTO path: a credit note created before the
            # return-detail fields existed is filled in on this sweep rather
            # than staying blank for good.
            _ensure_return_details(
                existing, client,
                package_code=customer_return.get("code"),
                reverse_pickup_code=customer_return.get("reversePickupCode"),
                return_type="CUSTOMER_RETURN",
            )


def create_cir_credit_note(so_data, return_data, client=None):
    sales_order_name = frappe.db.get_value("Sales Order", {ORDER_CODE_FIELD: so_data["code"]})
    so = frappe.get_doc("Sales Order", sales_order_name)

    # map SO item -> SI item via the linked child row
    so_item_code_map = {item.get(ORDER_ITEM_CODE_FIELD): item.name for item in so.items}

    invoice_name = frappe.db.get_value("Sales Invoice", {ORDER_CODE_FIELD: so_data["code"], "is_return": 0})
    if not invoice_name:
        # Same shape as create_rto_return's missing-invoice check -- a
        # customer return on an order that was never invoiced locally has
        # nothing to attach a credit note to.
        frappe.log_error(
            title="Unicommerce: customer return has no local Sales Invoice",
            message=f"Order {so_data['code']} has a Customer Returned return but no non-return "
                    f"Sales Invoice exists locally -- it was likely never invoiced.",
        )
        return
    si = frappe.get_doc("Sales Invoice", invoice_name)
    so_si_item_map = {item.so_detail: item.name for item in si.items}

    credit_note = create_credit_note(si.name)
    credit_note.set(TRACKING_CODE_FIELD, return_data.get("trackingNumber"))
    credit_note.set(SHIPPING_PROVIDER_CODE, return_data.get("shippingProvider"))
    apply_return_details(
        credit_note, client, credit_note.get(FACILITY_CODE_FIELD), "CUSTOMER_RETURN",
        shipment_code=return_data.get("code"),
        reverse_pickup_code=return_data.get("reversePickupCode"),
    )

    returned_so_codes = [item.get("saleOrderItemCode") for item in return_data.get("returnItems")]
    returned_si_items = [so_si_item_map.get(so_item_code_map.get(code)) for code in returned_so_codes]

    if set(returned_si_items) != set(so_si_item_map.values()):
        _handle_partial_returns(credit_note, returned_si_items)

    credit_note.save()
    credit_note.submit()


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
