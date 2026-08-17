# Unicommerce Connector — Technical Docs

Deep technical reference for engineers operating, extending, or onboarding a
new client onto this connector. For a plain-English overview see
`../what-it-does.md` and `../features.md`.

1. [Architecture](01-architecture.md) — flow directions, triggers, intervals
2. [Doctypes](02-doctypes.md) — every doctype, every field
3. [Channels](03-channels.md) — the multi-marketplace model
4. [Order flow](04-order-flow.md) — order pull, status, cancellation, returns
5. [Fulfillment](05-fulfillment.md) — delivery note, invoice, manifest
6. [Product & inventory](06-product-inventory.md) — product pull/push, inventory pull
7. [Client / API](07-client-api.md) — transport layer, every real endpoint
8. [Auth](08-auth.md) — token lifecycle and its failure modes
9. [Setup checklist](09-setup-checklist.md) — onboarding a new client/site
10. [Channel cloning runbook](10-channel-cloning-runbook.md) — copying channel setup to a new site
11. [Self-heal patterns](11-self-heal-patterns.md) — every idempotent fix baked into the connector
12. [Error visibility](12-error-visibility.md) — where failures actually show up
