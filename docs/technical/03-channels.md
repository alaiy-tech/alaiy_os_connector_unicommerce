# Unicommerce Channel — the multi-marketplace model

Unicommerce itself aggregates many real marketplaces (Amazon, Flipkart,
custom storefronts, Shopify-via-Unicommerce, etc.) behind one tenant,
distinguished by Unicommerce's own `channel` code on every order/package.

**One `Unicommerce Channel` row = one real channel.** Order pull filters
strictly to `enabled=1` channels — an order on a channel with no matching row
is silently skipped.

| Field | Role |
|---|---|
| `channel_id` (unique, autoname) | Must match Unicommerce's channel code exactly |
| `company` | Which Alaiy OS company this channel's orders post against — one Unicommerce tenant can serve multiple companies |
| `warehouse` | Default fulfillment warehouse if a line item's facility isn't separately mapped |
| `igst_account`, `cgst_account`, `sgst_account`, `ugst_account`, `tcs_account` | Tax posting accounts — must belong to `company` |
| `fnf_account`, `cod_account`, `gift_wrap_account` | Charges collected from the customer — income accounts, not expense |
| `cash_or_bank_account`, `cost_center` | Payment/cost posting |
| `sales_order_series`, `sales_invoice_series` | Per-channel naming series (falls back to Settings if unset) |
| `customer_group` | Per-channel customer bucketing (falls back to Settings' default) |
| `shipping_handled_by_marketplace` | Decides which invoicing endpoint is used — marketplace-shipped vs self-shipped |
| `auto_payment_entry`, `submit_payment_entry` | Auto-create (and optionally submit) a Payment Entry on invoice creation — for COD/marketplace-settled channels |

`_autofill_accounts()` (validate hook, runs before `_check_company()`) fills
any still-blank account field from the placeholder accounts
`setup/create_channel_accounts.py` bootstraps (`Output Tax IGST - <abbr>`,
`TCS Payable - <abbr>`, `Gift Wrap Charges Collected - <abbr>`, etc.) plus the
company's own default cost center / cash account — never overwrites a field
that already has a real value. This is why a newly created Channel often
already has most of its accounts filled in without anyone touching them.

`_check_company()` (validate hook) rejects the record if any linked
account/warehouse/cost-center doesn't belong to the Channel's own `company`.

This is how one Unicommerce tenant with N real marketplaces maps cleanly onto
N (possibly cross-company) accounting configurations on the Alaiy OS side.
