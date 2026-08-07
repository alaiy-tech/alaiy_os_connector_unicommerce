# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Unicommerce -> Alaiy OS Purchase Order sync.

Maps onto ERPNext's own Purchase Order / Purchase Order Item doctypes via
custom fields (see setup/install.py) -- same convention order/pull.py uses
for Sales Order, not a standalone mirror doctype.

Mirrors order/pull.py's shape otherwise: search for what's new/changed,
fetch full detail per code, upsert idempotently by the external code,
log-and-continue on a single PO's failure rather than aborting the batch.

One real wrinkle Sales Orders don't have: getPurchaseOrderDetails is scoped
by a Facility HEADER, not a body field, and the response carries no facility
code of its own to tell us which one to send. There's no single Unicommerce
call that resolves "which facility is this PO in" -- so every configured
facility (Unicommerce Warehouses) is tried in turn until one answers.
"""

import datetime

import frappe
from frappe.utils import add_days, cint, flt, get_datetime, now_datetime

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.purchase_order import (
    get_purchase_order_details, search_purchase_orders,
)
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    FACILITY_CODE_FIELD, ITEM_EXTERNAL_ID_FIELD, PO_CODE_FIELD, PO_STATUS_FIELD, PO_CURRENCY_FIELD,
    PO_ITEM_PENDING_QTY_FIELD, PO_ITEM_RECEIVED_QTY_FIELD, PO_ITEM_SKU_FIELD, PO_RAW_JSON_FIELD,
    PO_SYNCED_AT_FIELD, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.supplier import get_or_create_supplier

# Unicommerce's search takes one date range per call, no pagination -- a
# multi-year "pull everything" request is chunked into windows this size so
# one call isn't asked to cover an unbounded/huge span.
_CHUNK_DAYS = 90


def sync_purchase_orders(client: UnicommerceClient = None, force: bool = False):
    """Called from a scheduled job (see sync.py/run_po_sync) -- syncs every
    Purchase Order created since the last run."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled or not settings.sync_purchase_orders:
        return

    created_from = settings.last_po_sync or _default_start_date(settings)
    created_to = now_datetime()

    synced_to = sync_purchase_orders_for_range(created_from, created_to, client=client)
    if synced_to is not None:
        frappe.db.set_value(SETTINGS_DOCTYPE, None, "last_po_sync", synced_to, update_modified=False)
        frappe.db.commit()


def run_full_purchase_order_import(client: UnicommerceClient = None):
    """Pull the tenant's ENTIRE Purchase Order history, ignoring last_po_sync
    -- for a fresh site, or to backfill POs older than when sync was first
    turned on. Chunked so one huge date range is never sent in a single call.
    Does not advance last_po_sync -- a full import is explicit and repeatable,
    not meant to change what the next scheduled incremental run considers new."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if client is None:
        client = UnicommerceClient()

    start = get_datetime(_default_start_date(settings))
    end = now_datetime()

    window_start = start
    while window_start < end:
        window_end = min(add_days(window_start, _CHUNK_DAYS), end)
        sync_purchase_orders_for_range(window_start, window_end, client=client)
        window_start = window_end


def sync_purchase_orders_for_range(created_from, created_to, client: UnicommerceClient = None):
    """Pull every Purchase Order created in [created_from, created_to] and
    upsert it. Returns created_to on success (the caller decides whether that
    means anything as a checkpoint), or None if no facility is configured."""
    if client is None:
        client = UnicommerceClient()

    facility_codes = _get_facility_codes()
    if not facility_codes:
        frappe.log_error(
            title="Unicommerce: no facility configured, Purchase Order sync imported nothing",
            message=(
                "Purchase Order search/details are both Facility-scoped -- confirmed live, "
                "despite the docs calling search Tenant-level -- and no Unicommerce Warehouses "
                "row is configured/enabled locally. Add at least one Warehouse mapping."
            ),
        )
        return None

    # Search itself is Facility-scoped (confirmed live -- see
    # search_purchase_orders' docstring), so every configured facility is
    # searched in turn; a PO code found under one facility is then fetched
    # with THAT SAME facility, not re-tried across all of them.
    po_codes_by_facility = {}
    for facility_code in facility_codes:
        codes = search_purchase_orders(
            client, created_from=created_from, created_to=created_to, facility_code=facility_code)
        for code in codes or []:
            po_codes_by_facility.setdefault(code, facility_code)

    for po_code, facility_code in po_codes_by_facility.items():
        create_or_update_purchase_order(po_code, client=client, facility_codes=[facility_code])

    return created_to


def _default_start_date(settings):
    """No hardcoded epoch -- anchor a first-ever sync to a real date: the
    admin's explicit po_sync_start_date if set, else the Company's own
    creation date (the earliest point any of this data could be relevant)."""
    if settings.po_sync_start_date:
        return settings.po_sync_start_date
    return frappe.db.get_value("Company", settings.unicommerce_company, "creation") or now_datetime()


def _get_facility_codes() -> list[str]:
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    return [row.unicommerce_facility_code for row in settings.warehouse_mapping if row.enabled]


def create_or_update_purchase_order(po_code: str, client: UnicommerceClient = None, facility_codes=None):
    """Idempotent upsert by PO Code. Per-PO failures are logged and skipped
    -- never raised, so one bad PO can't stop the rest of the batch."""
    if client is None:
        client = UnicommerceClient()
    if facility_codes is None:
        facility_codes = _get_facility_codes()

    try:
        data, facility_used = _fetch_po_details(client, po_code, facility_codes)
        if data is None:
            frappe.log_error(
                title=f"Unicommerce: Purchase Order {po_code} not found on any configured facility",
                message=f"Tried facilities: {facility_codes}",
            )
            return None
        return _upsert_purchase_order(data, facility_used)
    except Exception:
        frappe.log_error(
            title=f"Unicommerce: failed to sync Purchase Order {po_code}",
            message=frappe.get_traceback(),
        )
        return None


def _fetch_po_details(client, po_code, facility_codes):
    for facility_code in facility_codes:
        data = get_purchase_order_details(client, po_code, facility_code=facility_code)
        if data:
            return data, facility_code
    return None, None


def _upsert_purchase_order(data: dict, facility_code: str | None):
    existing = frappe.db.get_value("Purchase Order", {PO_CODE_FIELD: data["code"]})
    if existing:
        return _update_existing_purchase_order(existing, data, facility_code)
    return _create_purchase_order(data, facility_code)


def _create_purchase_order(data: dict, facility_code: str | None):
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    supplier = get_or_create_supplier(data.get("vendorCode"), data.get("vendorName"))

    transaction_date = _epoch_ms_to_date(data.get("created")) or frappe.utils.nowdate()
    schedule_date = data.get("deliveryDate") or transaction_date

    items = _map_po_items(data.get("purchaseOrderItems") or [], schedule_date)
    if not items:
        frappe.log_error(
            title=f"Unicommerce: Purchase Order {data['code']} had no mappable items",
            message="No purchaseOrderItems resolved to a local Item -- see raw payload on the sync log.",
        )
        return None

    po = frappe.get_doc({
        "doctype": "Purchase Order",
        "supplier": supplier.name,
        "company": settings.unicommerce_company,
        "transaction_date": transaction_date,
        "schedule_date": schedule_date,
        PO_CODE_FIELD: data["code"],
        PO_STATUS_FIELD: data.get("statusCode"),
        FACILITY_CODE_FIELD: facility_code,
        PO_CURRENCY_FIELD: _get_custom_field(data, "Currency"),
        PO_RAW_JSON_FIELD: frappe.as_json(data),
        PO_SYNCED_AT_FIELD: now_datetime(),
        "items": items,
    })
    po.flags.ignore_permissions = True
    po.insert()
    po.submit()
    frappe.db.commit()
    return po


def _update_existing_purchase_order(po_name: str, data: dict, facility_code: str | None):
    """A Purchase Order already submitted can't have its item table freely
    rewritten -- only the safe, ever-changing bits (received/pending qty as
    goods arrive, the raw payload, sync timestamp) are patched directly,
    without touching docstatus or re-submitting."""
    frappe.db.set_value("Purchase Order", po_name, {
        PO_STATUS_FIELD: data.get("statusCode"),
        FACILITY_CODE_FIELD: facility_code,
        PO_CURRENCY_FIELD: _get_custom_field(data, "Currency"),
        PO_RAW_JSON_FIELD: frappe.as_json(data),
        PO_SYNCED_AT_FIELD: now_datetime(),
    })

    qty_by_sku = {
        item.get("itemSKU"): _received_pending(item)
        for item in (data.get("purchaseOrderItems") or [])
        if item.get("itemSKU")
    }
    po_items = frappe.get_all(
        "Purchase Order Item", filters={"parent": po_name}, fields=["name", PO_ITEM_SKU_FIELD])
    for row in po_items:
        received_pending = qty_by_sku.get(row.get(PO_ITEM_SKU_FIELD))
        if not received_pending:
            continue
        received_qty, pending_qty = received_pending
        frappe.db.set_value("Purchase Order Item", row.name, {
            PO_ITEM_RECEIVED_QTY_FIELD: received_qty,
            PO_ITEM_PENDING_QTY_FIELD: pending_qty,
        })

    frappe.db.commit()
    return frappe.get_doc("Purchase Order", po_name)


def _map_po_items(items: list, schedule_date) -> list[dict]:
    rows = []
    for item in items:
        sku = item.get("itemSKU")
        item_code = frappe.db.get_value("Item", {ITEM_EXTERNAL_ID_FIELD: sku}, "name") if sku else None
        if not item_code:
            continue

        received_qty, pending_qty = _received_pending(item)
        rows.append({
            "item_code": item_code,
            "qty": flt(item.get("quantity")),
            "rate": flt(item.get("unitPrice")),
            "schedule_date": schedule_date,
            PO_ITEM_SKU_FIELD: sku,
            PO_ITEM_RECEIVED_QTY_FIELD: received_qty,
            PO_ITEM_PENDING_QTY_FIELD: pending_qty,
        })
    return rows


def _received_pending(item: dict) -> tuple[float, float]:
    """Unicommerce's PO API has no direct "received quantity" field --
    derived from ordered - pending - rejected."""
    ordered_qty = flt(item.get("quantity"))
    pending_qty = flt(item.get("pendingQuantity"))
    rejected_qty = flt(item.get("rejectedQuantity"))
    received_qty = max(0.0, ordered_qty - pending_qty - rejected_qty)
    return received_qty, pending_qty


def _get_custom_field(data: dict, field_name: str) -> str:
    for cf in data.get("customFieldValues") or []:
        if cf.get("fieldName") == field_name:
            return cf.get("fieldValue") or ""
    return ""


def _epoch_ms_to_date(value):
    if not value:
        return None
    return datetime.datetime.fromtimestamp(cint(value) // 1000).date()
