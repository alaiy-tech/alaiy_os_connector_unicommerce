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

## Inventory pull — `inventory/pull.py` (the live direction)

Unicommerce → Alaiy OS. Runs every 5 minutes via cron, gated by
`enable_inventory_sync`, additionally interval-gated by
`inventory_sync_frequency` against `last_inventory_pull`.

For each mapped, non-group warehouse: fetches the Unicommerce inventory
snapshot (`inventory/inventorySnapshot/get`, chunked at 10,000 SKUs per
call — Unicommerce's own documented limit) for every Item with a real
Unicommerce SKU (`unicommerce_external_id` set — not gated by the "Sync to
Unicommerce" checkbox, which is an opt-in for pushing out, not a signal for
whether stock should be pulled in). Any SKU whose reported quantity differs
from the current `Bin.actual_qty` becomes one row in a **Stock
Reconciliation**, batched at up to 100 items per document (ERPNext
auto-backgrounds a submit past that threshold, which would hide a real
failure) — one real, audited Stock Reconciliation per warehouse per run, not
a raw Bin write. A facility mapped to a **group warehouse is skipped and
logged**, not aggregated/distributed — guessing how stock splits across
child warehouses would be inventing data.

Reserved/open-sale quantity is deliberately not subtracted — same
`actual_qty` convention the old push job used.

## Inventory push — `inventory/push.py` (dead code, not scheduled)

Alaiy OS → Unicommerce. The code still exists (per-warehouse bulk
`inventory/adjust/bulk` call with `adjustmentType: REPLACE`, up to 1000 SKUs
per request, gated by `enable_inventory_sync`) but its scheduler hook was
removed from `hooks.py` — nothing calls it anymore. Unicommerce is now the
sole system of record for physical stock; there is no live push direction.
