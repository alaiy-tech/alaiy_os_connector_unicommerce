# Product sync & inventory

## Product pull — `product/pull.py`

`import_product_from_unicommerce(sku)`:

- Maps every field via `product/mapping.py`.
- Links to an existing same-named Item instead of duplicating.
- Truncates over-length names to fit the target field.
- Resolves Item Group by matching `unicommerce_product_category`.
- Creates missing Brands.

## Product push — `product/push.py`

`upload_new_items` — rides the order-sync cron if
`upload_item_to_unicommerce` is on. Selects Items with `sync_to_unicommerce=1`
and no `unicommerce_external_id` yet (the idempotency marker); writes the
marker back on success.

## Bulk catalogue import — `product/bulk_import.py`

Paginated walk of the full Unicommerce catalogue (run via `bench execute`),
reusing the same pull function per missing SKU. Cross-checks
walked-vs-imported counts so nothing is silently dropped.

## Item Group sync — `setup/sync_item_groups.py`

Enumerates every category code/name pair seen in the catalogue (Unicommerce
has no dedicated category-list endpoint) and creates/links Item Groups.
Run this before a bulk catalogue import so Items land in real groups instead
of a flat default.

## Product validation — `product/validate.py`

Enforces the SKU pattern `[A-Za-z0-9._\-/]{3,45}` and requires an Item
Group's `unicommerce_product_category` to be set — only when
`sync_to_unicommerce` is checked and the connector is enabled.

## Inventory push — `inventory/push.py` (one-way only)

Every 5 minutes, gated by `enable_inventory_sync`. Per configured warehouse
(group warehouses consolidate every leaf stock bin), selects Items whose
stock changed since their last sync timestamp, batches up to 1000 SKUs per
request, calls the bulk adjust-inventory endpoint with
`adjustmentType: REPLACE`. The per-Item watermark only advances for SKUs
that succeeded across every warehouse they appear in.

There is deliberately no inventory pull direction — the Alaiy OS side is the
system of record for stock, never Unicommerce.
