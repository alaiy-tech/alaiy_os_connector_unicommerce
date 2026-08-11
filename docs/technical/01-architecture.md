# Architecture

Unicommerce is the warehouse/order-management system. Alaiy OS is the books
and stock system. This app is the bridge between them.

Nothing writes to Unicommerce unless a setting is explicitly turned on or a
button is pressed. Order/status import is always read-only pull.

## Flows

| Flow | Direction | Trigger | Interval |
|---|---|---|---|
| Order pull | Unicommerce → Alaiy OS | cron | `order_sync_frequency` (10/15/30/60 min) |
| Order status sync | Unicommerce → Alaiy OS | `hourly_long` | hourly |
| Cancellations & returns | Unicommerce → Alaiy OS | `hourly_long` | hourly |
| Delivery Note creation | Unicommerce → Alaiy OS | cron | every 5 min |
| Invoice + shipping label | Alaiy OS → Unicommerce | manual button / API | on demand |
| Product pull | Unicommerce → Alaiy OS | manual / bulk import job | on demand |
| Product push | Alaiy OS → Unicommerce | cron (if enabled) | rides `order_sync_frequency` |
| Inventory push | Alaiy OS → Unicommerce | cron | every 5 min |
| Purchase Order pull | Unicommerce → Alaiy OS | cron (if enabled) | `po_sync_frequency` |
| GRN push | Alaiy OS → Unicommerce | cron (if enabled) | rides PO interval |
| Manifest close | Alaiy OS → Unicommerce | manual (Submit) | on demand |

## Other docs in this set

- [02-doctypes.md](02-doctypes.md) — every doctype, every field
- [03-channels.md](03-channels.md) — the multi-marketplace model
- [04-order-flow.md](04-order-flow.md) — order pull, status, cancellation, returns
- [05-fulfillment.md](05-fulfillment.md) — delivery note, invoice, manifest
- [06-product-inventory.md](06-product-inventory.md) — product pull/push, inventory push
- [07-client-api.md](07-client-api.md) — transport layer, every real endpoint
- [08-auth.md](08-auth.md) — token lifecycle and its failure modes
- [09-setup-checklist.md](09-setup-checklist.md) — onboarding a new client/site
- [10-channel-cloning-runbook.md](10-channel-cloning-runbook.md) — copying channel setup to a new site
- [11-self-heal-patterns.md](11-self-heal-patterns.md) — every idempotent fix baked into the connector
- [12-error-visibility.md](12-error-visibility.md) — where failures actually show up
