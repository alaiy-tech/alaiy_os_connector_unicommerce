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

## Manifest — `Unicommerce Shipment Manifest`

A submittable doctype that batches Sales Invoices into one shipping
manifest. On submit:

1. Calls the create-and-close manifest endpoint.
2. Stores the returned manifest code/id.
3. Attaches the returned PDF.
4. Flags every linked Sales Invoice as manifested — blocks re-manifesting the
   same invoice a second time.
