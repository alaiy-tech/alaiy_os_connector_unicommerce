# Error visibility

Per-API-call failures go to the standard **Error Log** (via
`unicommerce/log.py:log_api_error`) — no dedicated per-call log doctype.

Run-level status lives on **Unicommerce Sync Log** (one row per sync run:
queued/running/success/failed, item counts, error message).

Check Sync Log first — "did this run and what happened" — then Error Log
for the exact underlying exception/API response.
