# Setup checklist for a new client/site

1. Install this app on the site.
2. Enable **Unicommerce Connector Settings** — tick `is_enabled` and save.
   This fires custom-field setup automatically, but **only on the 0→1
   transition** of that checkbox — installing the app alone does NOT
   provision the custom fields (`unicommerce_order_code` etc. on Sales
   Order/Invoice/Delivery Note/Item/...). Skipping this step is why a fresh
   site can throw `Unknown column 'unicommerce_order_code' in 'WHERE'` the
   first time any connector API (dashboard stats, order pull, ...) runs.
   - If the checkbox was already toggled without fields showing up (or the
     doc was inserted/patched directly, bypassing `on_update`), run the
     provisioning function directly instead of re-toggling:
     ```bash
     bench --site <site> execute alaiy_os_connector_unicommerce.setup.install.setup_custom_fields
     ```
3. Fill `unicommerce_site`, `username`, `password`, `client_id`,
   `unicommerce_company`, `default_customer_group`,
   `sales_order_series`/`sales_invoice_series`.
4. Add at least one **Unicommerce Warehouses** row (facility ↔ local
   warehouse). Required for inventory push, PO/GRN sync, and delivery note
   polling — all facility-scoped.
5. Add one **Unicommerce Channel** row per real marketplace this tenant
   sells through, `enabled=1`. **Order pull imports nothing at all until at
   least one channel exists** — this is the #1 "orders aren't syncing"
   report for a new client. See [03-channels.md](03-channels.md).
   - Each channel needs 8 GL accounts. Bootstrap placeholders with:
     ```bash
     bench --site <site> execute alaiy_os_connector_unicommerce.setup.create_channel_accounts.run --kwargs "{'company': '<Company>'}"
     ```
     These are placeholders to unblock setup, not real GST configuration —
     confirm with finance before going live. Only safe to introduce on a
     company with zero existing GL postings.
6. Optionally run `setup/sync_item_groups.py:sync()` before a bulk catalogue
   import, so Items land in pre-existing Item Groups instead of a flat
   default.
7. Test the connection via the connector's "Test Connection" action before
   relying on the scheduler — it validates credentials end-to-end
   (auth + a live API call) without side effects.
