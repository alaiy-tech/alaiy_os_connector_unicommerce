# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Item validate hook -- enforces Unicommerce's naming/category requirements
before an Item flagged for sync is even savable."""

import frappe
from frappe import _

from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ITEM_SYNC_CHECKBOX, PRODUCT_CATEGORY_FIELD, SETTINGS_DOCTYPE, UNICOMMERCE_SKU_PATTERN,
)


def validate_item(doc, method=None):
    """
    1. item_code must fulfil Unicommerce's SKU code requirements.
    2. The selected Item Group must have a Unicommerce product category.

    ref: http://support.unicommerce.com/index.php/knowledge-base/q-what-is-an-item-master-how-do-we-add-update-an-item-master/
    """
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled or not doc.get(ITEM_SYNC_CHECKBOX):
        return

    if not UNICOMMERCE_SKU_PATTERN.fullmatch(doc.item_code):
        msg = _("Item code is not valid as per Unicommerce requirements.") + "<br>"
        msg += _("Unicommerce allows 3-45 character long alpha-numeric SKU code") + " "
        msg += _("with four special characters: . _ - /")
        frappe.throw(msg, title=_("Invalid SKU for Unicommerce"))

    item_group = frappe.get_cached_doc("Item Group", doc.item_group)
    if not item_group.get(PRODUCT_CATEGORY_FIELD):
        frappe.throw(_("Unicommerce Product category required in Item Group: {0}").format(item_group.name))
