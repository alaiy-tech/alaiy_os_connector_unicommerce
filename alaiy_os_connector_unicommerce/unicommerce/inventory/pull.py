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
(docs/unicommerce-docs/client/product/search-itemtype.md):
  elements[].skuCode                          -> Item[ITEM_EXTERNAL_ID_FIELD]
                                                   (the same identity field
                                                   push.py already uses)
  elements[].inventorySnapshots[].inventory   -> Bin.actual_qty (the
                                                   "available quantity" --
                                                   openSale/reserved stock is
                                                   deliberately not
                                                   subtracted here, same as
                                                   push.py's own actual_qty
                                                   use)

Pulled via itemType/search with getInventorySnapshot=true, NOT the
inventorySnapshot/get endpoint -- confirmed live that endpoint only
returns SKUs updated within the last 24 hours (Unicommerce rejects any
wider window with "You can query for only one day snapshots"), so a
brand with a long tail of slow-moving SKUs never got an initial Bin row:
Quiz Clothing had stock rows for only 43 of 4,136 catalogue items, all
43 being the ones with recent order activity. itemType/search returns
current stock for every item regardless of when it last changed.

Group warehouses are skipped, not aggregated/distributed -- Stock
Reconciliation requires a real leaf warehouse; guessing how a Unicommerce
facility's stock should be split across ERPNext's child warehouses would
be inventing data, not pulling it.
"""

import frappe
from frappe.query_builder import DocType
from frappe.utils import cint, flt

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.inventory import search_itemtype_with_inventory
from alaiy_os_connector_unicommerce.unicommerce.constants import ITEM_EXTERNAL_ID_FIELD, SETTINGS_DOCTYPE
from alaiy_os_connector_unicommerce.unicommerce.utils import need_to_run

# Page size for itemType/search -- comfortably under any practical response
# size limit; the same 500-per-request ceiling that worked reliably for the
# old snapshot endpoint's batches.
SEARCH_PAGE_SIZE = 500

# Hard ceiling on total pages per warehouse per run, purely as a runaway
# guard against an unexpected totalRecords (e.g. a facility misconfiguration
# reporting far more items than the real catalogue) turning one run into an
# unbounded loop.
MAX_PAGES_PER_WAREHOUSE = 200

# ERPNext core auto-enqueues Stock Reconciliation submit as a background job
# once an item count exceeds this (stock_reconciliation.py's own threshold) --
# submit() then returns immediately without raising, leaving the doc queued/
# locked in draft until a worker picks it up. Keeping each Reconciliation at
# or under 100 items keeps every submit synchronous, so a real failure
# surfaces immediately instead of disappearing into a background job.
MAX_ITEMS_PER_RECONCILIATION = 100


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

    changes = []
    seen_skus = set()
    display_start = 0
    for _ in range(MAX_PAGES_PER_WAREHOUSE):
        response = search_itemtype_with_inventory(
            client, facility_code=facility_code,
            display_start=display_start, display_length=SEARCH_PAGE_SIZE,
        )
        if not response or not response.get("successful"):
            frappe.log_error(
                title=f"Unicommerce inventory pull: unsuccessful response for {warehouse} "
                f"(page starting at {display_start})",
                message=f"response={response}",
            )
            break

        elements = response.get("elements") or []
        for element in elements:
            item_code = sku_to_item.get(element.get("skuCode"))
            if not item_code:
                continue
            seen_skus.add(element.get("skuCode"))
            snapshots = element.get("inventorySnapshots") or []
            snapshot = next((s for s in snapshots if s.get("facility") == facility_code), None)
            if snapshot is None:
                continue
            new_qty = flt(snapshot.get("inventory"))
            current_qty = flt(frappe.db.get_value(
                "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
            ) or 0)
            if new_qty != current_qty:
                changes.append({"item_code": item_code, "warehouse": warehouse, "qty": new_qty})

        display_start += SEARCH_PAGE_SIZE
        total_records = response.get("totalRecords") or 0
        if display_start >= total_records or not elements:
            break

    missing_skus = set(sku_to_item.keys()) - seen_skus
    if missing_skus:
        # Not a failure -- some mapped SKUs may genuinely not exist in this
        # facility's catalogue (multi-facility items, since-delisted items).
        # Logged as a warning so a real coverage regression is visible
        # without treating every run as an error.
        frappe.log_error(
            title=f"Unicommerce inventory pull: {len(missing_skus)} mapped SKUs not found in {warehouse}",
            message=f"facility={facility_code}\nsample={list(missing_skus)[:50]}",
        )

    if not changes:
        return

    company = frappe.db.get_single_value(SETTINGS_DOCTYPE, "unicommerce_company")
    for i in range(0, len(changes), MAX_ITEMS_PER_RECONCILIATION):
        batch = changes[i:i + MAX_ITEMS_PER_RECONCILIATION]
        doc = frappe.new_doc("Stock Reconciliation")
        doc.company = company
        doc.purpose = "Stock Reconciliation"
        for change in batch:
            doc.append("items", {
                **change,
                # Confirmed live: without this, submit fails with "Valuation
                # Rate required" for any item that's never had a cost basis
                # recorded -- and ERPNext rejects the ENTIRE Stock
                # Reconciliation over one such row, so a single un-costed
                # item (PJBFT116, seen live) blocked every other item in the
                # same 100-item batch. Same fix already used in
                # pull_stock_from_shopify.py's equivalent reconciliation.
                "allow_zero_valuation_rate": 1,
            })
        doc.flags.ignore_permissions = True
        try:
            doc.insert(ignore_permissions=True)
            doc.submit()
        except Exception:
            frappe.db.rollback()
            # One bad batch must not stop every batch after it -- confirmed
            # live this loop has no such guard, so an early batch's failure
            # for ANY reason silently prevented every later batch for this
            # same warehouse from ever being attempted.
            frappe.log_error(
                title=f"Unicommerce inventory pull: batch reconciliation failed for {warehouse}",
                message=frappe.get_traceback(),
            )
            continue


def _get_synced_items() -> dict:
    """unicommerce_sku -> item_code, for every Item that actually has a
    Unicommerce SKU mapped. push.py's ITEM_SYNC_CHECKBOX ("Sync to
    Unicommerce") gate was tried here first and confirmed empty on real
    data (0 Items have it checked on Globali, so push.py itself was
    already a no-op) -- that flag is an opt-in for pushing OUT, not a
    signal for whether an item's real stock should be pulled IN. Any
    Item with a real SKU identity should have its stock kept accurate."""
    Item = DocType("Item")
    rows = (
        frappe.qb.from_(Item)
        .select(Item[ITEM_EXTERNAL_ID_FIELD].as_("sku"), Item.name.as_("item_code"))
        .where(Item[ITEM_EXTERNAL_ID_FIELD] != "")
        .run(as_dict=1)
    )
    return {row.sku: row.item_code for row in rows}
