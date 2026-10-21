"""Holds Unicommerce's blocked quantity on each Bin.

Bin.actual_qty is the available quantity the inventory pull reconciles to.
Unicommerce also reports the quantity it has committed to open orders (blocked),
and available plus blocked is the total stock on hand. Without this field the
total could not be shown, only the available part.

Existing Bins start empty and fill on the next inventory pull.

Idempotent -- safe to re-run.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Bin": [
            {
                "fieldname": "unicommerce_blocked_qty",
                "label": "Unicommerce Blocked Qty",
                "fieldtype": "Float",
                "default": "0",
                "insert_after": "actual_qty",
                "read_only": 1,
                "no_copy": 1,
                "description": (
                    "Stock Unicommerce has committed to open orders. Actual Qty is the "
                    "available quantity; Actual Qty plus this is the total on hand."
                ),
            },
        ]
    })
