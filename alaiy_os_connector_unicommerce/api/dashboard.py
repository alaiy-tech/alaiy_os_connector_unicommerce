# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Whitelisted read-only methods behind the Unicommerce desk page's stat cards,
plus desk-callable wrappers for the catalogue and category imports that were
previously only reachable via `bench execute`.

Local counts are cheap COUNT queries. The Unicommerce-side counts each cost an
API round trip, so they are a separate call the page loads after the local ones
have already rendered.
"""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ITEM_EXTERNAL_ID_FIELD, ITEM_SYNC_CHECKBOX, ORDER_CODE_FIELD, PRODUCT_CATEGORY_FIELD,
)


@frappe.whitelist()
def get_dashboard_stats() -> dict:
    """Counts drawn from the local site only -- no Unicommerce calls."""
    return {
        "items_total": frappe.db.count("Item"),
        "items_from_unicommerce": frappe.db.count("Item", {ITEM_EXTERNAL_ID_FIELD: (">", "")}),
        "items_flagged_for_push": frappe.db.count("Item", {ITEM_SYNC_CHECKBOX: 1}),
        "item_groups_mapped": frappe.db.count("Item Group", {PRODUCT_CATEGORY_FIELD: (">", "")}),
        "orders_synced": frappe.db.count("Sales Order", {ORDER_CODE_FIELD: (">", "")}),
        "invoices_synced": frappe.db.count("Sales Invoice", {ORDER_CODE_FIELD: (">", "")}),
        "channels_enabled": frappe.db.count("Unicommerce Channel", {"enabled": 1}),
        "channels_total": frappe.db.count("Unicommerce Channel"),
        "warehouse_mappings": frappe.db.count("Unicommerce Warehouses"),
    }


@frappe.whitelist()
def get_unicommerce_side_stats() -> dict:
    """Counts read live from Unicommerce. One API call each, so this is loaded
    separately from the local stats and is allowed to fail on its own."""
    from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
    from alaiy_os_connector_unicommerce.unicommerce.client.catalog import search_item_types

    client = UnicommerceClient()

    # display_length=1 -- we only want totalRecords, not the page of results.
    _, catalogue_total = search_item_types(client, display_start=0, display_length=1)

    facilities, _ = client.request(
        endpoint="/services/rest/v1/facility/search",
        body={
            "facilityStatus": "ALL",
            "dateType": "CREATED",
            # Unicommerce requires an explicit window; this one is wide enough
            # to cover any tenant's history without being unbounded.
            "fromDate": "2000-01-01T00:00:00.000Z",
            "toDate": "2100-01-01T00:00:00.000Z",
        },
    )

    return {
        "catalogue_items": catalogue_total or 0,
        "facilities": len((facilities or {}).get("parties") or []),
    }


@frappe.whitelist()
def trigger_catalogue_import():
    """Enqueue the full Unicommerce catalogue import (read-only, pull only)."""
    frappe.enqueue(
        "alaiy_os_connector_unicommerce.unicommerce.product.bulk_import.run",
        queue="long",
        timeout=7200,
        dry_run=False,
    )
    return {"queued": True, "message": "Catalogue import queued. Watch the Error Log for failures."}


@frappe.whitelist()
def trigger_item_group_sync():
    """Enqueue the Item Group / category sync (read-only against Unicommerce;
    writes Item Groups locally)."""
    frappe.enqueue(
        "alaiy_os_connector_unicommerce.setup.sync_item_groups.sync",
        queue="long",
        timeout=3600,
        dry_run=False,
    )
    return {"queued": True, "message": "Category sync queued."}


@frappe.whitelist()
def trigger_purchase_order_sync(from_date: str | None = None, to_date: str | None = None):
    """Enqueue a Purchase Order sync. With no dates, pulls the tenant's
    entire PO history (chunked). With both dates, pulls just that range --
    for a manual backfill of a specific window without waiting on the
    scheduled incremental job."""
    if from_date and to_date:
        frappe.enqueue(
            "alaiy_os_connector_unicommerce.unicommerce.purchase_order.pull.sync_purchase_orders_for_range",
            queue="long", timeout=3600, created_from=from_date, created_to=to_date,
        )
        return {"queued": True, "message": f"Purchase Order sync queued for {from_date} to {to_date}."}

    frappe.enqueue(
        "alaiy_os_connector_unicommerce.unicommerce.purchase_order.pull.run_full_purchase_order_import",
        queue="long", timeout=7200,
    )
    return {"queued": True, "message": "Full Purchase Order history import queued."}


@frappe.whitelist()
def trigger_grn_sync(from_date: str | None = None, to_date: str | None = None):
    """Enqueue a GRN sync. Same shape as trigger_purchase_order_sync --
    referencing Purchase Orders must already be synced locally, or a GRN
    that points at one not found here is logged and skipped."""
    if from_date and to_date:
        frappe.enqueue(
            "alaiy_os_connector_unicommerce.unicommerce.purchase_order.grn_pull.sync_grn_receipts_for_range",
            queue="long", timeout=3600, created_from=from_date, created_to=to_date,
        )
        return {"queued": True, "message": f"GRN sync queued for {from_date} to {to_date}."}

    frappe.enqueue(
        "alaiy_os_connector_unicommerce.unicommerce.purchase_order.grn_pull.run_full_grn_import",
        queue="long", timeout=7200,
    )
    return {"queued": True, "message": "Full GRN history import queued."}


@frappe.whitelist()
def get_recent_logs(limit: int = 10) -> list:
    """Recent sync log rows for the page's log table."""
    return frappe.get_all(
        "Unicommerce Sync Log",
        fields=[
            "name", "sync_type", "trigger", "status", "started_at", "finished_at",
            "items_processed", "items_created", "items_failed", "error_message",
        ],
        order_by="creation desc",
        limit=int(limit),
    )
