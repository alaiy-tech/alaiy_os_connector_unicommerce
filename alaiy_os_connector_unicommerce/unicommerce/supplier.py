# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Supplier resolution from Unicommerce Purchase Order vendor fields.
Same get-or-create shape as customer.py's sync_customer -- Unicommerce
doesn't dedupe vendors on its own either, so matching is done here by
vendor_code, the one stable identifier the PO API gives us."""

import frappe
from frappe.utils.nestedset import get_root_of

from alaiy_os_connector_unicommerce.unicommerce.constants import VENDOR_CODE_FIELD


def get_or_create_supplier(vendor_code: str, vendor_name: str):
    if vendor_code:
        existing = frappe.db.get_value("Supplier", {VENDOR_CODE_FIELD: vendor_code})
        if existing:
            return frappe.get_doc("Supplier", existing)

    supplier = frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": vendor_name or vendor_code or "Unicommerce Vendor",
        "supplier_group": get_root_of("Supplier Group"),
        "supplier_type": "Company",
        VENDOR_CODE_FIELD: vendor_code,
    })
    supplier.flags.ignore_mandatory = True
    supplier.insert(ignore_permissions=True)
    return supplier
