# Doctypes

| Doctype | Type | Purpose |
|---|---|---|
| **Unicommerce Connector Settings** | Single | Global config + OAuth token state |
| **Unicommerce Warehouses** | Child table (on Settings) | Facility code ↔ ERPNext warehouse mapping, RTO return warehouse, addresses |
| **Unicommerce Channel** | Standalone | One row per real marketplace — see [03-channels.md](03-channels.md) |
| **Unicommerce Sync Log** | Standalone | One row per sync run — status, counts, errors |
| **Unicommerce Shipment Manifest** | Submittable | Bulk-close a shipping manifest for a batch of packages |
| **Unicommerce Manifest Item** | Child table (on Manifest) | One row per package in a manifest |
| **Unicommerce Package Type** | Standalone | Box-size master, pushed back to Unicommerce |
| **Unicommerce Shipping Method** | Standalone | Reference master |
| **Unicommerce Shipping Provider** | Standalone | Reference master |
| **Pick List Unicommerce Order Detail** | Child table (on Pick List) | Per-SO pick status + invoice link |

## Unicommerce Connector Settings — key fields

| Field | Notes |
|---|---|
| `is_enabled` | Master on/off switch |
| `unicommerce_site`, `username`, `password`, `client_id` | Auth credentials (`client_id` defaults to `"my-trusted-client"`) |
| `access_token` / `refresh_token` / `expires_on` / `token_type` | Auto-managed — never edit by hand |
| `unicommerce_company`, `default_customer_group`, `default_item_group` | Fallback defaults when a Channel doesn't override them |
| `sales_order_series`, `sales_invoice_series` | Fallback naming series (reqd) |
| `order_status_days` | Order status sync looks back this many days (capped at 14 in code), default 2 |
| `delivery_note` | Enables the every-5-min Delivery Note pull off dispatched shipping packages |
| `order_sync_frequency` (Select: 1/5/10/15/30/60, default 30) | Order pull + product push cadence |
| `inventory_sync_frequency` (Select: 5/10/15/30/60, default 10) | Inventory pull is polled by cron every 5 min, then additionally gated by this interval against `last_inventory_pull` |
| `po_sync_frequency` (Select: 10/15/30/60, default 30) | Purchase Order + GRN pull cadence |
| `only_sync_completed_orders` | Filters which orders get pulled at all (only `COMPLETE` status when set) — no longer gates invoicing; a Sales Invoice is now attempted for every pulled order's packages that are already in an invoiced state on Unicommerce |
| `upload_item_to_unicommerce` | Enables product push |
| `enable_inventory_sync` | Gates the inventory pull (Unicommerce → Alaiy OS Stock Reconciliation) — despite the name, this no longer enables any push |
| `warehouse_mapping` | Table of `Unicommerce Warehouses` rows |
| `use_stock_entry_for_grn`, `vendor_code` | GRN **upload** config (Alaiy OS → Unicommerce, via Stock Entry submit) — separate section/concern from PO/GRN pull below |
| `sync_purchase_orders`, `po_sync_start_date`, `sync_grn_receipts` | PO/GRN **pull** config (Unicommerce → Alaiy OS); `sync_grn_receipts` rides `sync_purchase_orders`' schedule |
| `last_order_sync` / `last_inventory_sync` / `last_inventory_pull` / `last_po_sync` / `last_grn_sync` | Watermarks used by the frequency gate. `last_inventory_sync` is written by the (now-dead) push job; the live pull job advances `last_inventory_pull` |

## Unicommerce Warehouses (child table)

`unicommerce_facility_code`, `erpnext_warehouse` (real fieldname, unchanged), `enabled`,
`return_warehouse`, `company_address`, `dispatch_address`.

Required for inventory pull and PO/GRN/delivery-note polling — all of those
are facility-scoped.

## Purchase Order / GRN — custom fields, not new doctypes

Unlike Sales Orders, Purchase Orders and their GRNs map onto ERPNext's own
core doctypes via custom fields (`setup/install.py:setup_custom_fields`),
not a standalone mirror doctype:

| Doctype | Custom fields |
|---|---|
| **Purchase Order** | `unicommerce_po_code` (unique), `unicommerce_po_status` (Unicommerce's own status — separate from ERPNext's workflow status), `unicommerce_facility_code`, `unicommerce_currency`, `unicommerce_synced_at`, `unicommerce_raw_json` (hidden) |
| **Purchase Order Item** | `unicommerce_sku_code`, `unicommerce_received_qty` (derived: ordered − pending − rejected, not returned directly by Unicommerce), `unicommerce_pending_qty` |
| **Purchase Receipt** | `unicommerce_grn_code` (unique), `unicommerce_facility_code`, `unicommerce_synced_at`, `unicommerce_raw_json` (hidden) |
| **Supplier** | `unicommerce_vendor_code` |

A Purchase Order already submitted is never rewritten on re-sync — only
`unicommerce_po_status`, `unicommerce_facility_code`, `unicommerce_currency`,
`unicommerce_raw_json`, `unicommerce_synced_at`, and each item's
received/pending qty are patched in place.
