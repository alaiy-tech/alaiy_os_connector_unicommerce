# Self-heal patterns

The connector follows a "fix it once, automatically, every time" convention
rather than documenting a manual workaround. Recognize this shape when
reading the code — a helper that checks a condition and corrects it, called
unconditionally before the operation that depends on it.

| Helper | Fixes |
|---|---|
| `get_dummy_tax_category()` | Opts connector-created orders out of the local tax-rule engine — Unicommerce is the source of truth for tax amounts |
| `ensure_multiple_items_allowed()` | Same SKU repeated across multiple order lines (partial allocations) is legal on Unicommerce, blocked by default locally |
| `_fix_settings_as_single()` | Installing the app never marks the Settings doctype Single on its own — reapplied on every install/migrate |
| `_save_retry_once()` | Concurrent token-refresh race → retry once against a fresh doc |
| `_handle_refresh_token_expiry()` | 30-day refresh-token expiry → automatic password-grant re-login |
| `is_your_company_address=0` explicit set | The Address doctype's core validation reads this field unconditionally; a site missing it crashes every address creation |
| no-enabled-channel / no-facility guards | Fresh site silently importing zero orders/POs is a trap — surfaced as a loud, diagnosable error instead |
| `_backfill_shipping_charge_to_order` / `_verify_total` | Known real-world total drift between Unicommerce and the local total is surfaced as a comment, not a blocking failure |
| `setup_custom_fields()` on every `after_migrate` | A connector installed but never enabled used to crash any API that touched its custom fields — now provisioned unconditionally on every migrate, not gated behind first-enable |
| Payment entry isolated in its own try/except after the invoice is submitted and committed | A `make_payment_entry` failure can no longer roll back an already-submitted Sales Invoice's own GL entries |

When adding a new flow, follow this same convention: self-heal known
environment drift, and fail loudly (not silently) when a required master
record (channel, warehouse mapping) is simply absent.
