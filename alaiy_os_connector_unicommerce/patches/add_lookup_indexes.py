"""Indexes for the two lookups the sync runs once per shipping package.

Sales Invoice is looked up by its shipping package code and Delivery Note by
its shipment id. Neither column was indexed, so each lookup scanned the whole
table and took seconds, thousands of times a day, which kept the database busy
enough to slow every other request.

Idempotent -- safe to re-run.
"""

import frappe

INDEXES = (
    ("Sales Invoice", "unicommerce_shipping_package_code"),
    ("Delivery Note", "unicommerce_shipment_id"),
)


def execute():
    for doctype, column in INDEXES:
        if not frappe.db.has_column(doctype, column):
            continue
        frappe.db.add_index(doctype, [column], index_name=f"uni_{column}"[:60])
