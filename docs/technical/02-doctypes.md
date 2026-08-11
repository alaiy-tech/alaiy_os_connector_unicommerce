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
| `sales_order_series`, `sales_invoice_series` | Fallback naming series |
| `order_sync_frequency` (10/15/30/60), `inventory_sync_frequency`, `po_sync_frequency` | Cron cadence selects |
| `only_sync_completed_orders` | If set, invoices are created inline during order pull instead of waiting for the normal invoice flow |
| `upload_item_to_unicommerce` | Enables product push |
| `enable_inventory_sync` | Enables inventory push |
| `warehouse_mapping` | Table of `Unicommerce Warehouses` rows |
| `use_stock_entry_for_grn`, `vendor_code`, `sync_purchase_orders`, `po_sync_start_date`, `sync_grn_receipts` | PO/GRN pull config |
| `last_order_sync` / `last_inventory_sync` / `last_po_sync` / `last_grn_sync` | Watermarks used by the frequency gate |

## Unicommerce Warehouses (child table)

`unicommerce_facility_code`, `erpnext_warehouse` (real fieldname, unchanged), `enabled`,
`return_warehouse`, `company_address`, `dispatch_address`.

Required for inventory push and PO/GRN/delivery-note polling — all of those
are facility-scoped.
