# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Supplier resolution from Unicommerce Purchase Order vendor fields.
Same get-or-create shape as customer.py's sync_customer -- Unicommerce
doesn't dedupe vendors on its own either, so matching is done here by
vendor_code, the one stable identifier the PO API gives us."""

import re

import frappe
from frappe.utils.nestedset import get_root_of

from alaiy_os_connector_unicommerce.unicommerce.constants import VENDOR_CODE_FIELD

# Confirmed live: getPurchaseOrderDetails returns vendorName as a run of
# asterisks for at least some tenants (the vendor's real legal name is
# visible in Unicommerce's own admin UI but withheld from this API entirely
# -- there's no "get vendor" endpoint to fetch it another way). Same masking
# shape customer.py already handles for marketplace buyer names.
_MASKED_RE = re.compile(r"^\*+$")


def _is_masked(value) -> bool:
    return bool(value) and bool(_MASKED_RE.match(str(value).strip()))


def _refresh_placeholder_name(name: str, stored: str, vendor_code: str, vendor_name: str | None) -> None:
    """Replace a stored supplier name that is a masking artefact.

    A supplier first seen while its name was masked keeps that mask forever,
    because nothing re-reads the name afterwards. On a bench that predates
    `_is_masked` this leaves suppliers literally called `********` -- which
    is unreadable in any view grouping purchases by vendor, and vendor is
    the closest thing a consolidator has to a brand on the supply side.

    Only a placeholder is ever overwritten: a name a human has since
    corrected is left alone. The vendor code is used when Unicommerce still
    will not return a real name, because an opaque code still beats a row of
    asterisks.

    Uses `db.set_value` rather than `doc.save()` deliberately -- on a bench
    where Supplier is autonamed from `supplier_name`, saving would trigger a
    document rename from inside a sync loop. Every list and report reads the
    display field; `name` stays put as the stable key.
    """
    if not _is_masked(stored) and stored not in ("", None, "Unicommerce Vendor"):
        return
    better = vendor_name or vendor_code
    if not better or better == stored:
        return
    frappe.db.set_value("Supplier", name, "supplier_name", better, update_modified=False)


def get_or_create_supplier(vendor_code: str, vendor_name: str):
    if _is_masked(vendor_name):
        vendor_name = None

    if vendor_code:
        existing = frappe.db.get_value(
            "Supplier", {VENDOR_CODE_FIELD: vendor_code}, ["name", "supplier_name"], as_dict=True
        )
        if existing:
            _refresh_placeholder_name(
                existing.name, existing.supplier_name, vendor_code, vendor_name
            )
            return frappe.get_doc("Supplier", existing.name)

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
