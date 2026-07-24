# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Unicommerce -> Alaiy OS item import."""

import frappe
from frappe import _
from frappe.utils.nestedset import get_root_of
from stdnum.ean import is_valid as validate_barcode

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.catalog import get_unicommerce_item
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    DEFAULT_WEIGHT_UOM, ITEM_EXTERNAL_ID_FIELD, PRODUCT_CATEGORY_FIELD, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.product.mapping import UNI_TO_ITEM_FIELD


def import_product_from_unicommerce(sku: str, client: UnicommerceClient = None) -> None:
    """Pull one SKU's item data from Unicommerce into an Alaiy OS Item."""
    if not client:
        client = UnicommerceClient()

    response = get_unicommerce_item(client, sku)
    if not response:
        frappe.throw(_("Unicommerce item not found"))

    try:
        item = response["itemTypeDTO"]
        if _link_if_already_exists(item):
            return

        item_dict = _build_item_dict(item)
        doc = frappe.get_doc({"doctype": "Item", **item_dict})
        doc.flags.ignore_permissions = True
        doc.insert()
    except Exception:
        frappe.log_error(title=f"Unicommerce: failed to import item {sku}", message=frappe.get_traceback())
        raise


def _build_item_dict(uni_item: dict) -> dict:
    item_dict = {"weight_uom": DEFAULT_WEIGHT_UOM}
    _validate_create_brand(uni_item.get("brand"))

    for uni_field, erpnext_field in UNI_TO_ITEM_FIELD.items():
        value = uni_item.get(uni_field)
        if _is_valid_field_value(erpnext_field, value):
            item_dict[erpnext_field] = value

    item_dict["barcodes"] = _barcode_rows(uni_item)
    item_dict["disabled"] = int(not uni_item.get("enabled"))
    item_dict["item_group"] = _resolve_item_group(uni_item.get("categoryCode"))
    item_dict[ITEM_EXTERNAL_ID_FIELD] = uni_item["skuCode"]
    item_dict["name"] = item_dict["item_code"]  # naming is by item_code, not autoname series
    return item_dict


def _barcode_rows(uni_item: dict) -> list:
    barcodes = []
    ean, upc = uni_item.get("ean"), uni_item.get("upc")
    if ean and validate_barcode(ean):
        barcodes.append({"barcode": ean, "barcode_type": "EAN"})
    if upc and validate_barcode(upc):
        barcodes.append({"barcode": upc, "barcode_type": "UPC-A"})
    return barcodes


def _link_if_already_exists(uni_item: dict) -> bool:
    """A local Item with the same code (created by another connector, or
    manually) just needs the external-id field linked, not a duplicate
    created. Returns True if a match was found and linked."""
    sku = uni_item["skuCode"]
    if not frappe.db.exists("Item", sku):
        return False
    frappe.db.set_value("Item", sku, ITEM_EXTERNAL_ID_FIELD, sku)
    return True


def _validate_create_brand(brand):
    if brand and not frappe.db.exists("Brand", brand):
        frappe.get_doc(doctype="Brand", brand=brand).insert(ignore_permissions=True)


def _is_valid_field_value(fieldname: str, value) -> bool:
    """False if the field doesn't exist on Item, or (for a Link field) the
    linked document doesn't exist."""
    field = frappe.get_meta("Item").get_field(fieldname)
    if not field:
        return False
    if field.fieldtype != "Link":
        return True
    return bool(frappe.db.exists(field.options, value))


def _resolve_item_group(category_code) -> str:
    """Priority: Item Group with this category code linked -> configured
    default -> root of the Item Group tree."""
    item_group = frappe.db.get_value("Item Group", {PRODUCT_CATEGORY_FIELD: category_code})
    if category_code and item_group:
        return item_group

    default_item_group = frappe.db.get_single_value(SETTINGS_DOCTYPE, "default_item_group")
    if default_item_group:
        return default_item_group

    return get_root_of("Item Group")
