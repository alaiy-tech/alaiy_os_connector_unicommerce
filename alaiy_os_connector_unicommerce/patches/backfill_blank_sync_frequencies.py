# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Give blank sync-frequency settings their documented default.

The frequency fields all carry a default in the doctype JSON, but a default
only applies when a document is created. `Unicommerce Connector Settings` is
a Single, so on any bench where the Single row already existed when these
fields were added, the fields were left empty -- and stayed empty.

That is not a harmless blank. `sync_jobs._maybe_enqueue` parses the value
with `int()` and returns on failure, so an empty `po_sync_frequency` means
the Purchase Order sync is never enqueued at all, no matter that
`sync_purchase_orders` is ticked. Nothing reports it: the toggle reads as
on, the settings form looks configured, and the sync simply never runs.

Found on the Globali bench, where `sync_purchase_orders` had been enabled
for some time with `po_sync_frequency` empty. The 31 purchase orders that
had reached the site all carried sync timestamps from a single manual run,
and POs raised in Unicommerce afterwards had never arrived.
"""

import frappe

SETTINGS_DOCTYPE = "Unicommerce Connector Settings"
FREQUENCY_FIELDS = (
    "order_sync_frequency",
    "inventory_sync_frequency",
    "po_sync_frequency",
)


def execute():
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
        return

    meta = frappe.get_meta(SETTINGS_DOCTYPE)
    for fieldname in FREQUENCY_FIELDS:
        field = meta.get_field(fieldname)
        if not field or not field.default:
            continue

        current = str(frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname) or "").strip()
        if current.isdigit():
            continue

        frappe.db.set_value(
            SETTINGS_DOCTYPE, None, fieldname, field.default, update_modified=False
        )
        print(f"  {fieldname}: {current!r} -> {field.default!r}")
