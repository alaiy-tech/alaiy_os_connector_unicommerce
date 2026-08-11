# Cloning channel setup across sites

When a new company/site needs the same set of real marketplaces already
configured elsewhere (same client, second site; or a shared multi-brand
tenant), export the existing `Unicommerce Channel` rows and re-create them
against the new site's own company/warehouse/accounts.

**Never copy the `name`/`company`/account fields verbatim — they're
site-specific.**

## Step 1 — export on the source site

```python
import json, frappe
rows = [frappe.get_doc("Unicommerce Channel", n).as_dict()
        for n in frappe.get_all("Unicommerce Channel", pluck="name")]
keep = ["channel_id", "display_name", "globali_channel_type", "warehouse",
        "customer_group", "igst_account", "cgst_account", "sgst_account",
        "ugst_account", "tcs_account", "cash_or_bank_account", "fnf_account",
        "cod_account", "gift_wrap_account", "cost_center",
        "auto_payment_entry", "submit_payment_entry", "sales_order_series",
        "sales_invoice_series", "shipping_handled_by_marketplace"]
data = [{k: r.get(k) for k in keep} for r in rows]
path = frappe.get_site_path("public", "files", "unicommerce_channels.json")
with open(path, "w") as f:
    json.dump(data, f, indent=2)
```

Downloadable from `https://<source-site>/files/unicommerce_channels.json`.

## Step 2 — bootstrap accounts on the target site

```bash
bench --site <target-site> execute alaiy_os_connector_unicommerce.setup.create_channel_accounts.run --kwargs "{'company': '<Target Company>'}"
```

## Step 3 — insert on the target site, remapped

```python
import requests, frappe

data = requests.get("https://<source-site>/files/unicommerce_channels.json").json()

field_map = {
    "company": "<Target Company>",
    "warehouse": "<Target Warehouse>",
    "igst_account": "<Target IGST Account>",
    "cgst_account": "<Target CGST Account>",
    "sgst_account": "<Target SGST Account>",
    "ugst_account": "<Target UGST Account>",
    "tcs_account": "<Target TCS Account>",
    "cash_or_bank_account": "<Target Cash/Bank Account>",
    "fnf_account": "<Target Freight Account>",
    "cod_account": "<Target COD Account>",
    "gift_wrap_account": "<Target Gift Wrap Account>",
    "cost_center": "<Target Cost Center>",
}

created, skipped = [], []
for row in data:
    if frappe.db.exists("Unicommerce Channel", row["channel_id"]):
        skipped.append(row["channel_id"])
        continue
    doc = frappe.new_doc("Unicommerce Channel")
    doc.update(row)
    doc.update(field_map)
    doc.customer_group = None  # review/set manually — source-site-specific
    doc.insert()
    created.append(row["channel_id"])

frappe.db.commit()
print(len(created), "created:", created)
print(len(skipped), "skipped (already exist):", skipped)
```

`channel_id`, `display_name`, `globali_channel_type`,
`shipping_handled_by_marketplace`, `auto_payment_entry`,
`submit_payment_entry` carry over unchanged — everything else is
company-specific and must be remapped, never inserted as-is.

`customer_group` in particular is frequently business-specific per site —
review/set manually after import, don't carry it over blind.
