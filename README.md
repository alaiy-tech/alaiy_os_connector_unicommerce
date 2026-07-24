# Alaiy OS Connector Template

A [Frappe](https://frappeframework.com) app scaffold for building a new **Alaiy OS connector** — an integration app that syncs Alaiy OS (Items, Orders, Stock, ...) with an external channel (e.g. Shopify) or supplier (e.g. Cloudstore). Clone this template, rename `template`/`Template` throughout, fill in the TODOs, and you have a connector that plugs straight into the Alaiy OS workspace, sidebar, and Connector Registry with no changes needed on the `alaiy_os` core side.

This template already implements every piece of plumbing a connector needs — registry registration, a settings form with a live status card, a sync log with scheduler support, and the Test Connection flow. What's left for you to fill in is the part that's actually specific to your integration: the HTTP client and the sync logic itself.

## What a connector is, in this architecture

`alaiy_os` (core) owns one thing connectors all plug into: the **`OS Connector Registry`** DocType, plus a generic API to read/configure/test whatever row is selected (`alaiy_os.api.connectors`). Core never contains connector-specific code. Every connector — this template included — is its own separate Frappe app that:

1. Registers itself into that registry on every `bench migrate` (`connector_meta.py` → `setup/install.py:sync_connector_registry()`).
2. Owns its own settings (a Single DocType holding credentials/config).
3. Owns its own sync logic and log history.
4. Points the registry at its own methods via dotted Python paths — core calls them, but never knows what's inside them.

That separation is why installing or removing a connector app never requires touching `alaiy_os` itself, and why this template only needs a rename + fill-in-the-blanks to become a real connector.

## Prerequisites

- A Frappe v16 / ERPNext v16 bench with `alaiy_os` already installed (`required_apps = ["alaiy_os", "erpnext"]` in `hooks.py` — bench will refuse to install this app without it).
- Python ≥ 3.14 (see `pyproject.toml`).

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app alaiy_os_connector_template /path/to/this/repo
bench install-app alaiy_os_connector_template
bench --site <site> migrate
bench build --app alaiy_os_connector_template
```

---

## Turning this into a real connector

Do these in order. "Template"/"template" appears in class names, DocType names, field name prefixes, module paths, and the doc strings below — a global find/replace (case-sensitive, in this order: `Template` → `YourConnector`, `template` → `yourconnector`) handles almost all of it; the checklist below covers what a plain text replace *won't* catch (directory/file renames, and values you actually need to think about rather than mechanically substitute).

### 1. Rename the app itself

Frappe apps are named by their folder + `hooks.py`, not by an in-repo config flag:

- Rename both nested folders: `alaiy_os_connector_template/` (outer repo) and the inner `alaiy_os_connector_template/alaiy_os_connector_template/` package to your app name (e.g. `alaiy_os_connector_acme`).
- In `hooks.py`: `app_name`, `app_title`, `app_description`, and every dotted path (`after_install`, `after_migrate`, `scheduler_events`, `alaiy_os_sidebar_log_items`) must point at the new module path.
- `modules.txt` — the one line here (`Alaiy Os Connector Template`) is the Frappe "Module" your DocTypes are grouped under; rename it, and update the `module` field inside each DocType's `.json` and each Custom Field's `module` value in `setup/install.py` to match.
- `pyproject.toml` — `[project].name`.

### 2. Rename the two DocTypes

- `template_connector_settings/` → `<yourconnector>_connector_settings/`, DocType name `Template Connector Settings` → `<Your Connector> Settings`. Update every `template_*` fieldname prefix (`template_api_url`, `template_api_token`, `template_company`, `template_default_warehouse`, `template_price_list`, `template_pull_sync_interval`, `template_push_sync_interval`) to your own prefix, in the `.json`, the `.py` controller, and the `.js` client script.
- `template_sync_log/` → `<yourconnector>_sync_log/`, DocType name `Template Sync Log` → `<Your Connector> Sync Log`.
- **The settings DocType's `.json` does not declare `issingle: 1`.** This is intentional, not an oversight — `setup/install.py:_fix_settings_as_single()` force-patches `issingle=1` directly in the DB on every migrate, because Frappe won't reliably flip an existing table-based DocType to Single via the normal JSON sync. Keep that patch (renamed) rather than trying to set `issingle` in the JSON.

### 3. Fill in `connector_meta.py`

This dict is registered into `OS Connector Registry` verbatim — get it right and the workspace/sidebar/settings UI all just work:

| Key | What to set it to |
|---|---|
| `connector_id` | A short, permanent slug (e.g. `"acme"`). Never rename this later — it's the registry row's primary key and everything else (log filtering, connector card mounting) is keyed off it. |
| `connector_type` | `"channel"` if you sell **to** it (like Shopify), `"supplier"` if you buy **from** it (like Cloudstore). |
| `settings_doctype` | Your renamed settings DocType. |
| `test_method` | Dotted path to your `test_connection()` (see below). |
| `sync_categories_method` / `sync_items_method` | The registry only exposes **two** sync "slots" with configurable labels — map them to whatever two directions your integration actually has (pull/push, orders/inventory, categories/items, ...). The template maps them to generic pull/push; rename the labels (`sync_categories_label`/`sync_items_label`) to describe what they really do (e.g. "Orders" / "Inventory" for a channel connector). |
| `sync_status_method` | Returns recent log rows for the connector card; the template's version already maps registry slot names back to this connector's own `sync_type` values — update that mapping if you rename `pull`/`push`. |
| `icon` | A [Lucide](https://lucide.dev) icon name shown in the workspace card and sidebar. |

### 4. Implement the actual integration

- **`template/client.py`** → rename to your domain (e.g. `acme/client.py`). Replace the REST `get`/`post` helpers with whatever your API actually speaks (REST, GraphQL, SOAP, SDK). Keep the pattern of reading credentials once from the settings Single in `__init__` — every caller should go through one client, not re-read settings ad hoc.
- **`template/sync.py`** → `run_pull_sync` / `run_push_sync` are stubs (`pass`). Implement the real upsert logic against ERPNext (Item, Sales Order, Stock Entry, ...), updating the log's `items_processed`/`items_created`/`items_updated`/`items_failed`/`pages_total`/`pages_done` counters as you go. Keep `_run()`'s queued → running → success/failed bookkeeping wrapper — the connector card and Logs list depend on log status being accurate even when a sync throws.
- **`api/test_connection.py`** → point `test_connection()` at a real lightweight authenticated endpoint on your API. Always return `{"success": bool, "message": str}` — never let it raise, the settings form's "Test Connection" button and `alaiy_os.api.connectors.save_and_test` both depend on that contract.
- **`api/sync.py`** → thin wrappers only. If you renamed `pull`/`push`, update `trigger_pull_sync`/`trigger_push_sync`'s names and the `type_map` inside `get_sync_status`.
- **`template/sync_jobs.py`** → `check_and_enqueue()` runs every minute (wired in `hooks.py`'s `scheduler_events`) and decides whether a sync is actually due based on the interval Select fields in settings, skipping if one's already running (with a 30-minute staleness guard against a crashed job blocking the schedule forever) or if the last success is still within the interval. Rename `pull`/`push` here to match step 4 above; the interval/guard logic itself rarely needs changing.
- **Settings fields** (`template_connector_settings.json`) — the template ships API URL + Token, and Company/Warehouse/Price List defaults for mapping into ERPNext. Add/remove fields for whatever your integration actually needs (webhook secrets, store domain, API version, etc.).
- **`setup/install.py:setup_custom_fields()`** — replace the example `Item` custom fields (`template_external_id`, `sync_to_template`) with the external-ID / flag fields your connector needs on `Item` (or other DocTypes). This runs once, lazily, on the settings' 0→1 `is_enabled` transition (see `template_connector_settings.py:_on_first_enable()`) — **not** on every migrate, so installing the app stays cheap until an admin actually opts in. If your connector needs heavier one-time setup (default Supplier, Price Lists, Item Attributes — see the Cloudstore/Shopify connectors for examples), add it to `_on_first_enable()` too.
- Optional, commented-out in `hooks.py`: `doc_events` (react to Item/Sales Order changes) and `doctype_list_js` (inject a client script into a stock ERPNext list view) — uncomment and wire up only if your connector needs them.

### 5. Consider the shared generic DocTypes in core

Before modeling supplier attributes, per-supplier stock availability, or channel-listing state yourself, check whether `alaiy_os`'s `Item Supplier Attribute`, `Supplier Item Availability`, or `Channel Listing` (provisioned by `alaiy_os.setup.install.provision_shared_doctypes()`) already fit — they exist specifically so connectors don't each reinvent the same shape.

---

## How the pieces fit together at runtime

**Registration.** `sync_connector_registry()` runs on every `after_migrate`, upserting `connector_meta` into `OS Connector Registry` (idempotent — safe to run repeatedly) and re-running `alaiy_os`'s own workspace/sidebar provisioning immediately after, so your connector's settings link, connector card, and Logs entry appear without waiting for a full site migrate.

**Enabling.** A connector installs disabled (`is_enabled: 0`). An admin opens the settings form and checks "Enable" — the DocType controller's `validate()`/`on_update()` detects the 0→1 transition and runs `_on_first_enable()` (custom fields, and whatever else your integration needs set up once), and mirrors the flag onto the registry row so the workspace card reflects it.

**Testing the connection.** The settings form's "Test Connection" button calls `alaiy_os.api.connectors.test_connector` (the registry wrapper), **not** your `test_connection()` directly — going through the wrapper is what updates the registry's `connection_status`/`last_tested_at`, which is what flips the connector card from "Not configured" to "Connected".

**Syncing.** `api/sync.py`'s whitelisted `trigger_*_sync` functions create/reuse a Sync Log row (so the UI shows "queued" immediately) and enqueue the real work on the `long` queue — nothing runs synchronously in a web request. The scheduled path goes through `sync_jobs.check_and_enqueue()` instead, gated by the interval settings and a stale-running guard.

**Status reporting.** `get_sync_status()` feeds both the connector card (via the registry's `sync_status_method`) and can be called directly for a richer Logs view. `Template Sync Log` list view (`template_sync_log_list.js`) color-codes `sync_type`/`trigger`/`status` as pills for quick scanning.

**UI.** The settings form mounts `alaiy_os.connector_card.mount(frm, "<connector_id>")` — a shared component owned by core that renders the icon/name/status card. It's deliberately just status: your form adds its own Test Connection / Run Sync buttons to the Actions menu, keeping the shared component decoupled from what any given connector's buttons do. `setup_password_reveal()` is another shared helper — wire it onto any Password field you want reveal-on-focus behaviour for.

---

## File reference

| Path | Role |
|---|---|
| `hooks.py` | App manifest — name/dependencies, install/migrate hooks, sidebar log registration, scheduler cron. |
| `connector_meta.py` | Single source of truth for this connector's `OS Connector Registry` row. |
| `setup/install.py` | `after_install` (one-time cleanup), `sync_connector_registry` (registry upsert, every migrate), `setup_custom_fields` (first-enable only), plus reusable Single-doctype migration helpers (`_backfill_singles_defaults`, `_drop_orphaned_singles_value`, `_ensure_list_view_column`) for when your settings schema evolves. |
| `api/test_connection.py` | Whitelisted reachability check — wired as `connector_meta["test_method"]`. |
| `api/sync.py` | Whitelisted trigger/status endpoints the connector card and settings form call — stay thin, delegate to `template/sync.py`. |
| `template/client.py` | HTTP client built from saved settings — the one place credentials/auth headers live. |
| `template/sync.py` | Real sync logic + the Sync Log queued→running→success/failed lifecycle helpers. |
| `template/sync_jobs.py` | Scheduler entry point — decides what's due and enqueues it. |
| `alaiy_os_connector_template/doctype/template_connector_settings/` | Single DocType: credentials, ERPNext defaults, sync intervals. `.js` mounts the shared connector card and Actions buttons. |
| `alaiy_os_connector_template/doctype/template_sync_log/` | One row per sync run; `.js` list view color-codes status. |
| `.pre-commit-config.yaml`, `.eslintrc`, `.editorconfig`, `pyproject.toml` | Lint/format tooling (ruff, eslint, prettier, pyupgrade) — see Contributing below. |

---

## Before you ship it

- [ ] `bench --site <site> install-app <yourconnector>`
- [ ] `bench --site <site> migrate` — confirm the registry row appears under OS Settings → Connectors and the Sync Log link appears under Logs.
- [ ] `bench build --app <yourconnector>`
- [ ] Enable the connector from its settings form; confirm first-enable setup (custom fields, etc.) actually ran.
- [ ] Test Connection succeeds against real credentials and the connector card flips to "Connected".
- [ ] Both sync directions run manually from the Actions menu and produce a `success` log with sane counters.
- [ ] Leave the scheduled interval on for a few cycles and confirm `check_and_enqueue` fires correctly and doesn't double-run.
- [ ] Disable the connector and confirm `_on_disable()` cleans up whatever it should (webhooks, etc.).

## Contributing

This app uses `pre-commit` for formatting/linting (ruff, eslint, prettier, pyupgrade):

```bash
cd apps/<yourconnector>
pre-commit install
```

## License

AGPL-3.0 (`license.txt`) — matches `app_license` in `hooks.py`.
