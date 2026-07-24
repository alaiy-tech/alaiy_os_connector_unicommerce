# Alaiy OS Connector — Unicommerce

A [Frappe](https://frappeframework.com) app integrating Alaiy OS (Items, Orders, Stock, ...) with **Unicommerce** (WMS/OMS). Plugs straight into the Alaiy OS workspace, sidebar, and Connector Registry with no changes needed on the `alaiy_os` core side.

## What a connector is, in this architecture

`alaiy_os` (core) owns one thing connectors all plug into: the **`OS Connector Registry`** DocType, plus a generic API to read/configure/test whatever row is selected (`alaiy_os.api.connectors`). Core never contains connector-specific code. This connector is its own separate Frappe app that:

1. Registers itself into that registry on every `bench migrate` (`connector_meta.py` → `setup/install.py:sync_connector_registry()`).
2. Owns its own settings (a Single DocType holding credentials/config).
3. Owns its own sync logic and log history.
4. Points the registry at its own methods via dotted Python paths — core calls them, but never knows what's inside them.

## Prerequisites

- A Frappe v16 / ERPNext v16 bench with `alaiy_os` already installed (`required_apps = ["alaiy_os", "erpnext"]` in `hooks.py` — bench will refuse to install this app without it).
- Python ≥ 3.14 (see `pyproject.toml`).

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app alaiy_os_connector_unicommerce /path/to/this/repo
bench install-app alaiy_os_connector_unicommerce
bench --site <site> migrate
bench build --app alaiy_os_connector_unicommerce
```

---

## Status

Scaffolded from the connector template, renamed throughout. The actual Unicommerce integration is not yet implemented:

- **`unicommerce/client.py`** — HTTP client stub, needs Unicommerce's real API (auth flow, base URL shape).
- **`unicommerce/sync.py`** — `run_pull_sync`/`run_push_sync` are empty stubs; real upsert logic against ERPNext (Item, Sales Order, Stock Entry, ...) still needs building.
- **`api/test_connection.py`** — points at a placeholder `/ping` endpoint; needs a real Unicommerce reachability check.
- **`connector_meta.py`** — `connector_type` set to `"supplier"` (Unicommerce is a WMS/OMS, not a sales channel) as a starting assumption; confirm this matches how Alaiy OS actually uses it (inventory/fulfillment source vs. order channel) before shipping.
- **Settings fields** (`unicommerce_connector_settings.json`) — ships API URL + Token, Company/Warehouse/Price List defaults. Add whatever Unicommerce-specific fields are needed (facility code, API version, webhook secret, etc.).
- **`setup/install.py:setup_custom_fields()`** — still has the example `unicommerce_external_id`/`sync_to_unicommerce` placeholder fields; replace with whatever Item (or other doctype) fields the real integration needs.

---

## How the pieces fit together at runtime

**Registration.** `sync_connector_registry()` runs on every `after_migrate`, upserting `connector_meta` into `OS Connector Registry` (idempotent — safe to run repeatedly) and re-running `alaiy_os`'s own workspace/sidebar provisioning immediately after, so the connector's settings link, connector card, and Logs entry appear without waiting for a full site migrate.

**Enabling.** The connector installs disabled (`is_enabled: 0`). An admin opens the settings form and checks "Enable" — the DocType controller's `validate()`/`on_update()` detects the 0→1 transition and runs `_on_first_enable()` (custom fields, and whatever else the integration needs set up once), and mirrors the flag onto the registry row so the workspace card reflects it.

**Testing the connection.** The settings form's "Test Connection" button calls `alaiy_os.api.connectors.test_connector` (the registry wrapper), **not** `test_connection()` directly — going through the wrapper is what updates the registry's `connection_status`/`last_tested_at`, which is what flips the connector card from "Not configured" to "Connected".

**Syncing.** `api/sync.py`'s whitelisted `trigger_*_sync` functions create/reuse a Sync Log row (so the UI shows "queued" immediately) and enqueue the real work on the `long` queue — nothing runs synchronously in a web request. The scheduled path goes through `sync_jobs.check_and_enqueue()` instead, gated by the interval settings and a stale-running guard.

**Status reporting.** `get_sync_status()` feeds both the connector card (via the registry's `sync_status_method`) and can be called directly for a richer Logs view. `Unicommerce Sync Log` list view (`unicommerce_sync_log_list.js`) color-codes `sync_type`/`trigger`/`status` as pills for quick scanning.

**UI.** The settings form mounts `alaiy_os.connector_card.mount(frm, "unicommerce")` — a shared component owned by core that renders the icon/name/status card. `setup_password_reveal()` is another shared helper, wired onto the API Token field for reveal-on-focus.

---

## File reference

| Path | Role |
|---|---|
| `hooks.py` | App manifest — name/dependencies, install/migrate hooks, sidebar log registration, scheduler cron. |
| `connector_meta.py` | Single source of truth for this connector's `OS Connector Registry` row. |
| `setup/install.py` | `after_install` (one-time cleanup), `sync_connector_registry` (registry upsert, every migrate), `setup_custom_fields` (first-enable only), plus reusable Single-doctype migration helpers (`_backfill_singles_defaults`, `_drop_orphaned_singles_value`, `_ensure_list_view_column`) for when the settings schema evolves. |
| `api/test_connection.py` | Whitelisted reachability check — wired as `connector_meta["test_method"]`. |
| `api/sync.py` | Whitelisted trigger/status endpoints the connector card and settings form call — stay thin, delegate to `unicommerce/sync.py`. |
| `unicommerce/client.py` | HTTP client built from saved settings — the one place credentials/auth headers live. |
| `unicommerce/sync.py` | Real sync logic + the Sync Log queued→running→success/failed lifecycle helpers. |
| `unicommerce/sync_jobs.py` | Scheduler entry point — decides what's due and enqueues it. |
| `alaiy_os_connector_unicommerce/doctype/unicommerce_connector_settings/` | Single DocType: credentials, ERPNext defaults, sync intervals. `.js` mounts the shared connector card and Actions buttons. |
| `alaiy_os_connector_unicommerce/doctype/unicommerce_sync_log/` | One row per sync run; `.js` list view color-codes status. |
| `.pre-commit-config.yaml`, `.eslintrc`, `.editorconfig`, `pyproject.toml` | Lint/format tooling (ruff, eslint, prettier, pyupgrade) — see Contributing below. |

---

## Before you ship it

- [ ] `bench --site <site> install-app alaiy_os_connector_unicommerce`
- [ ] `bench --site <site> migrate` — confirm the registry row appears under OS Settings → Connectors and the Sync Log link appears under Logs.
- [ ] `bench build --app alaiy_os_connector_unicommerce`
- [ ] Enable the connector from its settings form; confirm first-enable setup (custom fields, etc.) actually ran.
- [ ] Test Connection succeeds against real credentials and the connector card flips to "Connected".
- [ ] Both sync directions run manually from the Actions menu and produce a `success` log with sane counters.
- [ ] Leave the scheduled interval on for a few cycles and confirm `check_and_enqueue` fires correctly and doesn't double-run.
- [ ] Disable the connector and confirm `_on_disable()` cleans up whatever it should (webhooks, etc.).

## Contributing

This app uses `pre-commit` for formatting/linting (ruff, eslint, prettier, pyupgrade):

```bash
cd apps/alaiy_os_connector_unicommerce
pre-commit install
```

## License

AGPL-3.0 (`license.txt`) — matches `app_license` in `hooks.py`.
