# Delivery Note, Invoice, Manifest

## Delivery Note — `unicommerce/fulfillment/delivery_note.py`

Every 5 minutes, guarded by the `delivery_note` checkbox on Settings. Polls
`DISPATCHED` shipping packages, skips if a Delivery Note already exists for
that shipment or the Sales Order/Invoice isn't found locally yet, then
creates the Delivery Note from the Sales Order.

## Invoice — `unicommerce/fulfillment/invoice.py`

Manual/API trigger (`generate_unicommerce_invoices`) — a single order runs
inline, multiple orders queue `bulk_generate_invoices`.

Per shipping package: calls one of two Unicommerce endpoints depending on
`Unicommerce Channel.shipping_handled_by_marketplace` (marketplace-shipped vs
self-shipped/assign-your-own-courier), then re-fetches once the package
reaches an invoiced state and creates the Sales Invoice.

Two deliberate soft-fail checks, both comment instead of throw:

- **Shipping charge backfill** — the real shipping cost is only known at
  invoice time, so it's pushed back onto the Sales Order additively, with a
  drift-detection comment if the running total looks off, rather than a hard
  failure.
- **Grand total verification** — if the Sales Invoice's grand total doesn't
  match Unicommerce's reported total, a comment is added so the mismatch is
  visible without blocking the invoice.

Payment entry creation is isolated from invoice submission: the invoice is
submitted and committed first, then `make_payment_entry` runs in its own
try/except. A payment-entry failure (e.g. a false-positive "already fully
paid" on freshly-submitted data) is logged but can no longer roll back the
invoice's own submit and GL entries. `update_stock` on the Sales Invoice is
forced to `0` whenever the `delivery_note` setting is on (the Delivery Note
is what deducts stock in that case) and is otherwise left at the caller's
default of `0` — stock accuracy at invoice time is a known, separately
tracked gap, not something invoicing is blocked on.

## Purchase Order / GRN pull — `unicommerce/purchase_order/pull.py`, `grn_pull.py`

Unicommerce → Alaiy OS, both gated off by default (`sync_purchase_orders`,
`sync_grn_receipts`).

- **Purchase Order pull**: searches for POs created in a date window (default
  start: `po_sync_start_date`, or the Company's own creation date), chunked
  into 90-day windows. Both search and detail-fetch are Facility-scoped —
  every configured `Unicommerce Warehouses` facility is tried in turn.
  Idempotent upsert by `unicommerce_po_code`; a PO already submitted is only
  ever patched (status, currency, raw JSON, received/pending qty per item),
  never re-inserted or re-submitted. A PO with no line item that resolves to
  a local Item is skipped and logged, not created empty.
- **GRN pull**: for each configured facility, searches Unicommerce inflow
  receipts and, per new receipt, builds a Purchase Receipt off the matching
  Purchase Order (`make_purchase_receipt`), trimmed down to only the items
  and quantities that receipt actually covers. GRNs are treated as immutable
  once received — an existing `unicommerce_grn_code` is never re-synced. A
  receipt referencing a Purchase Order not yet synced locally is logged and
  skipped, not force-created.
- Both are independent from `unicommerce/fulfillment/grn.py`'s Stock
  Entry → Unicommerce upload, which is the opposite direction and predates
  this pull.

## Manifest — `Unicommerce Shipment Manifest`

A submittable doctype that batches Sales Invoices into one shipping
manifest. On submit:

1. Calls the create-and-close manifest endpoint.
2. Stores the returned manifest code/id.
3. Attaches the returned PDF.
4. Flags every linked Sales Invoice as manifested — blocks re-manifesting the
   same invoice a second time.
