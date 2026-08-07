# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Unicommerce -> Alaiy OS GRN sync: each Unicommerce inflow receipt (goods
actually received against a Purchase Order) becomes a Purchase Receipt.

Same shape as purchase_order/pull.py, and reuses the same trim-to-this-event
pattern the Shopify connector's fulfillment sync uses for Delivery Notes:
build the full document from make_purchase_receipt(po_name), then cut every
row down to only what THIS receipt covers.

Unlike Purchase Order search (Tenant-level), both GRN endpoints are
Facility-level on Unicommerce's side -- search itself needs the Facility
header, so there's no facility-guessing here, each configured facility is
searched and fetched in its own scope.
"""

import frappe
from frappe.utils import add_days, flt, get_datetime, now_datetime

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.purchase_order import (
    get_inflow_receipt, search_inflow_receipts,
)
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    GRN_CODE_FIELD, GRN_RAW_JSON_FIELD, GRN_SYNCED_AT_FIELD, FACILITY_CODE_FIELD,
    ITEM_EXTERNAL_ID_FIELD, PO_CODE_FIELD, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.purchase_order.pull import _default_start_date, _get_facility_codes

_CHUNK_DAYS = 90


def sync_grn_receipts(client: UnicommerceClient = None, force: bool = False):
    """Called from a scheduled job (see sync.py/run_po_sync) -- syncs every
    GRN created since the last run, across every configured facility."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled or not settings.sync_grn_receipts:
        return

    created_from = settings.last_grn_sync or _default_start_date(settings)
    created_to = now_datetime()

    synced_to = sync_grn_receipts_for_range(created_from, created_to, client=client)
    if synced_to is not None:
        frappe.db.set_value(SETTINGS_DOCTYPE, None, "last_grn_sync", synced_to, update_modified=False)
        frappe.db.commit()


def run_full_grn_import(client: UnicommerceClient = None):
    """Pull the tenant's ENTIRE GRN history, ignoring last_grn_sync. Chunked,
    same reasoning as run_full_purchase_order_import. Does not advance
    last_grn_sync."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if client is None:
        client = UnicommerceClient()

    start = get_datetime(_default_start_date(settings))
    end = now_datetime()

    window_start = start
    while window_start < end:
        window_end = min(add_days(window_start, _CHUNK_DAYS), end)
        sync_grn_receipts_for_range(window_start, window_end, client=client)
        window_start = window_end


def sync_grn_receipts_for_range(created_from, created_to, client: UnicommerceClient = None):
    """Pull every GRN created in [created_from, created_to] across every
    configured facility. Returns created_to on success, or None if no
    facility is configured at all."""
    if client is None:
        client = UnicommerceClient()

    facility_codes = _get_facility_codes()
    if not facility_codes:
        frappe.log_error(
            title="Unicommerce: no facility configured, GRN sync imported nothing",
            message="Add at least one enabled Unicommerce Warehouses row -- GRN search is facility-scoped.",
        )
        return None

    for facility_code in facility_codes:
        receipt_codes = search_inflow_receipts(
            client, created_from=created_from, created_to=created_to, facility_code=facility_code)
        for receipt_code in receipt_codes or []:
            create_or_update_purchase_receipt(receipt_code, facility_code, client=client)

    return created_to


def create_or_update_purchase_receipt(receipt_code: str, facility_code: str, client: UnicommerceClient = None):
    """Idempotent upsert by GRN Code. Per-receipt failures are logged and
    skipped -- never raised, so one bad GRN can't stop the rest of the batch."""
    if client is None:
        client = UnicommerceClient()

    try:
        if frappe.db.exists("Purchase Receipt", {GRN_CODE_FIELD: receipt_code}):
            return None  # GRNs are immutable once received on Unicommerce's side -- nothing to update

        data = get_inflow_receipt(client, receipt_code, facility_code=facility_code)
        if data is None:
            frappe.log_error(
                title=f"Unicommerce: GRN {receipt_code} not found on facility {facility_code}",
                message="",
            )
            return None
        return _create_purchase_receipt(data, facility_code)
    except Exception:
        frappe.log_error(
            title=f"Unicommerce: failed to sync GRN {receipt_code}",
            message=frappe.get_traceback(),
        )
        return None


def _create_purchase_receipt(data: dict, facility_code: str):
    po_code = (data.get("purchaseOrder") or {}).get("code")
    po_name = frappe.db.get_value("Purchase Order", {PO_CODE_FIELD: po_code}) if po_code else None
    if not po_name:
        frappe.log_error(
            title=f"Unicommerce: GRN {data.get('code')} references PO {po_code}, not found locally",
            message="Sync the referencing Purchase Order first, or it hasn't landed yet.",
        )
        return None

    qty_by_sku = {
        item.get("itemSKU"): flt(item.get("quantity"))
        for item in (data.get("inflowReceiptItems") or [])
        if item.get("itemSKU")
    }
    if not qty_by_sku:
        return None

    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

    pr = make_purchase_receipt(po_name)

    kept_items = []
    for row in pr.items:
        sku = frappe.db.get_value("Item", row.item_code, ITEM_EXTERNAL_ID_FIELD)
        received_qty = qty_by_sku.get(sku, 0)
        if received_qty <= 0:
            continue
        row.qty = min(row.qty, received_qty)
        kept_items.append(row)
    pr.items = kept_items
    if not pr.items:
        return None

    pr.set(GRN_CODE_FIELD, data["code"])
    pr.set(FACILITY_CODE_FIELD, facility_code)
    pr.set(GRN_RAW_JSON_FIELD, frappe.as_json(data))
    pr.set(GRN_SYNCED_AT_FIELD, now_datetime())
    pr.flags.ignore_permissions = True
    pr.insert()
    pr.submit()
    frappe.db.commit()
    return pr
