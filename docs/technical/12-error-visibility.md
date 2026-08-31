# Error visibility

Per-API-call failures go to the standard **Error Log** (via
`unicommerce/log.py:log_api_error`) — no dedicated per-call log doctype.

Run-level status lives on **Unicommerce Sync Log** (one row per sync run:
queued/running/success/failed, item counts, error message).

Check Sync Log first — "did this run and what happened" — then Error Log
for the exact underlying exception/API response.

## Two real failure modes fixed, worth knowing about

- **`get_sales_invoice` returning `None`** (invoice pull, `order/pull.py`) —
  happens on any API failure, e.g. the Unicommerce account's credentials
  lacking the invoice-detail resource scope. Used to crash with a raw
  `TypeError` on `invoice_data["invoice"]`; now logged to Error Log with the
  package/order named, and skipped cleanly — same package retried next pull.
- **Payment Entry creation failing right after a Sales Invoice submits**
  (`fulfillment/invoice.py::create_sales_invoice`) — confirmed live: a
  `make_payment_entry` failure (e.g. an "already fully paid" false positive
  on data that had just submitted cleanly) rolled back the WHOLE
  transaction, wiping the invoice's own just-created GL Entries even though
  the invoice document itself (docstatus=1) survived. Fixed by committing
  right after a successful `si.submit()`, then isolating the payment step in
  its own try/except — a payment failure now only logs to Error Log, it can
  never undo the invoice.
