# Order pull, status, cancellation, returns

## Order pull — `unicommerce/order/pull.py`

- **Trigger**: cron every minute calls `sync_jobs.check_and_enqueue`, which
  enqueues `sync.run_pull_sync` once `order_sync_frequency` has elapsed since
  `last_order_sync`.
- `_get_new_orders`: `search_sales_order(updated_since=24h)`, filtered to
  `enabled=1` channels. **If zero channels are enabled, this logs an explicit
  error instead of silently importing nothing** — the single most common
  "why aren't orders syncing" cause for a newly onboarded client.
- `create_order`: idempotent by `unicommerce_order_code`. Missing Items are
  imported inline via `product.pull.import_product_from_unicommerce`.
  Customer resolved/created via `customer.sync_customer`.
- `_create_order`: sets `tax_category = get_dummy_tax_category()` (tax
  amounts come straight from Unicommerce, not computed by the local tax
  engine) and calls `ensure_multiple_items_allowed()` before insert — a
  single Unicommerce order can repeat the same SKU across multiple
  `saleOrderItems` lines (partial allocations/batches), which is blocked by
  default.
- `only_sync_completed_orders` only filters which orders get **pulled**
  (only Unicommerce-status `COMPLETE` orders, when set) — it no longer gates
  invoicing. On every pull, a Sales Invoice is attempted for any shipping
  package already in `fulfillment/invoice.py`'s `INVOICED_STATE` set
  (`PACKED`/`READY_TO_SHIP`/`DISPATCHED`/`MANIFESTED`/`SHIPPED`/`DELIVERED`),
  regardless of the setting — a freshly-placed order still in `CREATED` has
  no packages in that set yet, so nothing is attempted for it until it
  actually ships.

## Order status sync — `unicommerce/order/status.py`

`hourly_long`.

- `update_sales_order_status`: pulls status for orders updated in the last
  `order_status_days` (capped at 14), dispatches by bucket:
  `CANCELLED` → full cancel, `PENDING_VERIFICATION/CREATED/PROCESSING` →
  partial-item reconciliation, `COMPLETE` → customer-return check.
- `update_shipping_package_status`: per enabled facility, updates
  `unicommerce_shipping_package_status`; `RETURN_EXPECTED`/`RETURNED`
  triggers `create_rto_return`.

## Cancellations & returns — `unicommerce/order/cancellation.py`

Returns come in two distinct shapes from Unicommerce's own data:

- **Courier Returned (RTO)** — `create_rto_return` → `create_credit_note`,
  items reassigned to the facility's configured `return_warehouse`.
- **Customer Returned (CIR)** — `sync_customer_initiated_returns`, dedup by
  `unicommerce_return_code`; partial returns prune non-returned rows and
  rescale each tax row's `item_wise_tax_detail` proportionally to returned
  quantity.

Partial cancellations reuse the standard child-qty-rate update path rather
than deleting and re-adding rows, and are only applied while the Sales Order
is still in a draft/submitted (not-cancelled) state.
