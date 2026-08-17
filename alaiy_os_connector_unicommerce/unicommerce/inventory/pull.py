# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Pull Unicommerce's real warehouse-wise stock into ERPNext -- the missing
other half of push.py. Unicommerce is the source of truth for what's
physically in a facility (manual warehouse ops, other channels' fulfillment,
etc never flow back through ERPNext otherwise); without this, ERPNext's Bin
drifts from reality and invoice-time stock deduction (create_sales_invoice's
update_stock=1) eventually goes negative for exactly the items that drifted.

One real, audited Stock Reconciliation per warehouse per run (not one per
item) -- same "real accounting document, not a raw Bin write" convention as
every other connector in this codebase.

Field mapping confirmed against the real vendored Unicommerce docs
(docs/unicommerce-docs/client/inventory/inventory-snapshot.md):
  inventorySnapshots[].itemTypeSKU -> Item[ITEM_EXTERNAL_ID_FIELD] (the same
                                       identity field push.py already uses)
  inventorySnapshots[].inventory   -> Bin.actual_qty (the "available
                                       quantity" -- openSale/reserved stock
                                       is deliberately not subtracted here,
                                       same as push.py's own actual_qty use)

Group warehouses are skipped, not aggregated/distributed -- Stock
Reconciliation requires a real leaf warehouse; guessing how a Unicommerce
facility's stock should be split across ERPNext's child warehouses would
be inventing data, not pulling it.
"""

import frappe
from frappe.query_builder import DocType
from frappe.utils import cint, flt

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.inventory import get_inventory_snapshot
from alaiy_os_connector_unicommerce.unicommerce.constants import ITEM_EXTERNAL_ID_FIELD, ITEM_SYNC_CHECKBOX, SETTINGS_DOCTYPE
from alaiy_os_connector_unicommerce.unicommerce.utils import need_to_run

MAX_SKUS_PER_REQUEST = 10000  # Unicommerce's own documented limit per call


def pull_inventory_from_unicommerce(client=None, force: bool = False):
    """Pull Unicommerce's current stock per configured warehouse into a
    Stock Reconciliation. Called by the scheduler; force=True ignores the
    interval gate (same convention as the push job it replaces)."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled or not settings.enable_inventory_sync:
        return

    if not force and not need_to_run(SETTINGS_DOCTYPE, "inventory_sync_frequency", "last_inventory_pull"):
        return

    if client is None:
        client = UnicommerceClient()

    wh_to_facility_map = settings.get_erpnext_to_integration_wh_mapping()

    for warehouse, facility_code in wh_to_facility_map.items():
        if cint(frappe.db.get_value("Warehouse", warehouse, "is_group")):
            frappe.log_error(
                title=f"Unicommerce inventory pull: skipped group warehouse {warehouse}",
                message="Stock Reconciliation needs a real leaf warehouse; this facility mapping "
                "points at a group warehouse, which would require guessing how stock splits "
                "across its children -- not attempted.",
            )
            continue
        try:
            _pull_warehouse(client, warehouse, facility_code)
        except Exception:
            frappe.log_error(
                title=f"Unicommerce inventory pull failed for {warehouse}",
                message=frappe.get_traceback(),
            )
    frappe.db.commit()


def _pull_warehouse(client, warehouse, facility_code):
    sku_to_item = _get_synced_items()
    if not sku_to_item:
        return

    sku_codes = list(sku_to_item.keys())
    changes = []
    for i in range(0, len(sku_codes), MAX_SKUS_PER_REQUEST):
        batch = sku_codes[i:i + MAX_SKUS_PER_REQUEST]
        response = get_inventory_snapshot(client, sku_codes=batch, facility_code=facility_code)
        if not response or not response.get("successful"):
            continue
        for row in response.get("inventorySnapshots") or []:
            item_code = sku_to_item.get(row.get("itemTypeSKU"))
            if not item_code:
                continue
            new_qty = flt(row.get("inventory"))
            current_qty = flt(frappe.db.get_value(
                "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
            ) or 0)
            if new_qty != current_qty:
                changes.append({"item_code": item_code, "warehouse": warehouse, "qty": new_qty})

    if not changes:
        return

    doc = frappe.new_doc("Stock Reconciliation")
    doc.company = frappe.db.get_single_value(SETTINGS_DOCTYPE, "unicommerce_company")
    doc.purpose = "Stock Reconciliation"
    for change in changes:
        doc.append("items", change)
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    doc.submit()


def _get_synced_items() -> dict:
    """unicommerce_sku -> item_code, for every Item flagged to sync with
    Unicommerce -- same filter push.py uses for the opposite direction."""
    Item = DocType("Item")
    rows = (
        frappe.qb.from_(Item)
        .select(Item[ITEM_EXTERNAL_ID_FIELD].as_("sku"), Item.name.as_("item_code"))
        .where((Item[ITEM_SYNC_CHECKBOX] == 1) & (Item[ITEM_EXTERNAL_ID_FIELD] != ""))
        .run(as_dict=1)
    )
    return {row.sku: row.item_code for row in rows}
