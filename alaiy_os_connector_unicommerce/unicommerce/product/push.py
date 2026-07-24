# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Alaiy OS -> Unicommerce item push. Items with sync_to_unicommerce checked
and no unicommerce_external_id yet are pushed on a schedule; the successful
create/update writes the Unicommerce SKU back onto unicommerce_external_id,
which then also acts as the idempotency marker for "already pushed."
"""

from typing import NewType

import frappe
from frappe import _
from frappe.utils import get_url, now

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.catalog import create_update_item, get_unicommerce_item
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ITEM_EXTERNAL_ID_FIELD, ITEM_SYNC_CHECKBOX, PRODUCT_CATEGORY_FIELD, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.product.mapping import ITEM_FIELD_TO_UNI

ItemCode = NewType("ItemCode", str)


def upload_new_items(force: bool = False) -> None:
    """Push every not-yet-synced Item flagged sync_to_unicommerce. Wired to
    run on a schedule (see hooks.py); `force` lets the "Force Sync" button
    bypass the enabled/toggle checks for a manual one-off run."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not force and not (settings.is_enabled and settings.upload_item_to_unicommerce):
        return

    new_items = _get_new_items()
    if not new_items:
        return

    synced_items = upload_items_to_unicommerce(new_items)
    unsynced_items = set(new_items) - set(synced_items)
    if unsynced_items:
        frappe.log_error(
            title="Unicommerce: item push had failures",
            message=f"Synced: {', '.join(synced_items)}\nUnsynced: {', '.join(unsynced_items)}",
        )


def _get_new_items() -> list:
    return frappe.get_all(
        "Item",
        filters={ITEM_SYNC_CHECKBOX: 1, ITEM_EXTERNAL_ID_FIELD: ["in", ["", None]]},
        pluck="item_code",
    )


def upload_items_to_unicommerce(item_codes: list, client: UnicommerceClient = None) -> list:
    """Push multiple items to Unicommerce. Returns the item codes that
    actually succeeded."""
    if not client:
        client = UnicommerceClient()

    synced_items = []
    for item_code in item_codes:
        item_data = build_unicommerce_item(item_code)
        sku = item_data.get("skuCode")

        item_exists = bool(get_unicommerce_item(client, sku, log_error=False))
        _response, status = create_update_item(client, item_data, update=item_exists)

        if status:
            frappe.db.set_value("Item", item_code, ITEM_EXTERNAL_ID_FIELD, sku)
            synced_items.append(item_code)

    return synced_items


def build_unicommerce_item(item_code) -> dict:
    """Build the Unicommerce itemType JSON payload from an ERPNext Item."""
    item = frappe.get_doc("Item", item_code)
    item_json = {}

    for erpnext_field, uni_field in ITEM_FIELD_TO_UNI.items():
        value = item.get(erpnext_field)
        if value is not None:
            item_json[uni_field] = value

    item_json["enabled"] = not bool(item.get("disabled"))

    for barcode in item.barcodes:
        if not item_json.get("scanIdentifier"):
            item_json["scanIdentifier"] = barcode.barcode  # first barcode is the scan identifier
        if barcode.barcode_type == "EAN":
            item_json["ean"] = barcode.barcode
        elif barcode.barcode_type == "UPC-A":
            item_json["upc"] = barcode.barcode

    item_json["categoryCode"] = frappe.db.get_value("Item Group", item.item_group, PRODUCT_CATEGORY_FIELD)
    item_json["imageUrl"] = get_url(item.image) if item.image else None  # absolute URL, not the relative path
    item_json["maxRetailPrice"] = item.standard_rate
    item_json["description"] = frappe.utils.strip_html_tags(item.description) if item.description else ""
    item_json["costPrice"] = item.valuation_rate
    item_json["skuCode"] = item.item_code

    return item_json
