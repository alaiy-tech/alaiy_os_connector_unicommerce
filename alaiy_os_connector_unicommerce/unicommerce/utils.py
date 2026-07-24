# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Small shared helpers used across the Unicommerce sync modules."""

import datetime

import frappe

SYNC_METHODS = {
    "Items": "alaiy_os_connector_unicommerce.unicommerce.product.push.upload_new_items",
    "Orders": "alaiy_os_connector_unicommerce.unicommerce.order.pull.sync_new_orders",
    "Inventory": "alaiy_os_connector_unicommerce.unicommerce.inventory.push.update_inventory_on_unicommerce",
}

DOCUMENT_URL_FORMAT = {
    "Sales Order": "https://{site}/order/orderitems?orderCode={code}",
    "Sales Invoice": "https://{site}/order/orderitems?orderCode={code}",
    "Item": "https://{site}/products/edit?sku={code}",
    "Unicommerce Shipment Manifest": "https://{site}/manifests/edit?code={code}",
    "Stock Entry": "https://{site}/grns",
}


@frappe.whitelist()
def get_unicommerce_document_url(code: str, doctype: str) -> str:
    if not isinstance(code, str):
        frappe.throw(frappe._("Invalid Document code"))

    site = frappe.db.get_single_value("Unicommerce Connector Settings", "unicommerce_site", cache=True)
    url = DOCUMENT_URL_FORMAT.get(doctype, "")
    return url.format(site=site, code=code)


@frappe.whitelist()
def force_sync(document: str) -> None:
    frappe.only_for("System Manager")

    method = SYNC_METHODS.get(document)
    if not method:
        frappe.throw(frappe._("Unknown method"))
    frappe.enqueue(method, queue="long", is_async=True, force=True)


@frappe.whitelist()
def get_naming_series_options() -> dict:
    """Naming series choices offered on Unicommerce Channel's series select fields."""
    return {
        "sales_order_series": frappe.get_meta("Sales Order").get_options("naming_series"),
        "sales_invoice_series": frappe.get_meta("Sales Invoice").get_options("naming_series"),
        "delivery_note_series": frappe.get_meta("Delivery Note").get_options("naming_series"),
    }


def get_unicommerce_date(timestamp: int) -> datetime.date:
    """Convert a Unicommerce ms timestamp to a date."""
    return datetime.date.fromtimestamp(timestamp // 1000)


def remove_non_alphanumeric_chars(filename: str) -> str:
    return "".join(c for c in filename if c.isalpha() or c.isdigit()).strip()


def need_to_run(setting: str, interval_field: str, timestamp_field: str) -> bool:
    """
    Configurable-frequency scheduled-job gate. If timestamp_field is older
    than now - interval_field (minutes), updates timestamp_field to now()
    and returns True; otherwise False.

    Assumes: interval_field is in minutes, timestamp_field is a Datetime
    field, and this is called from a job scheduled MORE often than the
    smallest configured interval (ideally every minute) -- otherwise a run
    could be skipped entirely between checks.
    """
    from frappe.utils import add_to_date, cint, get_datetime, now

    interval = frappe.db.get_single_value(setting, interval_field, cache=True)
    last_run = frappe.db.get_single_value(setting, timestamp_field)

    if last_run and get_datetime() < get_datetime(add_to_date(last_run, minutes=cint(interval, default=10))):
        return False

    frappe.db.set_value(setting, None, timestamp_field, now(), update_modified=False)
    return True


DUMMY_TAX_CATEGORY = "Unicommerce - Ignore Tax Templates"


def get_dummy_tax_category() -> str:
    """A Tax Category that exists purely so transactions this connector
    creates can opt out of ERPNext's tax rule engine -- Unicommerce/channel
    tax amounts are set directly, not computed from a template."""
    if not frappe.db.exists("Tax Category", DUMMY_TAX_CATEGORY):
        frappe.get_doc(doctype="Tax Category", title=DUMMY_TAX_CATEGORY).insert(ignore_permissions=True)
    return DUMMY_TAX_CATEGORY


def validate_tax_template(doc, method=None):
    """Item validate hook: prevent the dummy tax category from being used in
    a real Item Tax Template (it must only ever be set directly on a
    transaction by this connector)."""
    for row in doc.get("taxes", []):
        if row.get("tax_category") == DUMMY_TAX_CATEGORY:
            frappe.throw(
                frappe._("Tax category '{0}' cannot be used in any tax templates.").format(DUMMY_TAX_CATEGORY)
            )
