# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Fill in a missing brand on items that already exist locally.

An item is copied from Unicommerce once, the first time it appears on an order.
If its Brand field was empty in Unicommerce at that moment, the local item kept
no brand, and nothing re-read it afterwards, so setting the brand in
Unicommerce later never reached the local item. Anything grouped by brand
(brand views, targets, margins) then left those items out.

This looks again, once a day, only at items that have no brand, and only fills
the brand in -- an item that has one is never touched. Written with a direct
column update so it does not trigger the Item events that push changes back to
Unicommerce.

Bounded and resumable: a fixed batch per run, and an item Unicommerce still has
no brand for is not asked about again for a day.
"""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.catalog import get_unicommerce_item
from alaiy_os_connector_unicommerce.unicommerce.constants import ITEM_EXTERNAL_ID_FIELD, SETTINGS_DOCTYPE

BATCH = 200
#: How long an item Unicommerce still has no brand for is left alone.
RECHECK_SECONDS = 24 * 60 * 60
CHECKED_KEY = "unicommerce_brand_checked"


def fill_missing_brands(limit: int = BATCH) -> dict:
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return {"skipped": "connector disabled"}

    skus = frappe.get_all(
        "Item",
        filters={ITEM_EXTERNAL_ID_FIELD: ["is", "set"], "brand": ["is", "not set"]},
        pluck=ITEM_EXTERNAL_ID_FIELD,
        order_by="modified desc",
        limit=limit * 3,
    )
    cache = frappe.cache()
    pending = [sku for sku in dict.fromkeys(skus) if sku and not cache.get_value(f"{CHECKED_KEY}:{sku}")][:limit]
    if not pending:
        return {"checked": 0, "filled": 0}

    client = UnicommerceClient()
    filled = failed = 0
    for sku in pending:
        try:
            response = get_unicommerce_item(client, sku)
            brand = ((response or {}).get("itemTypeDTO") or {}).get("brand")
            if not brand:
                cache.set_value(f"{CHECKED_KEY}:{sku}", 1, expires_in_sec=RECHECK_SECONDS)
                continue
            if not frappe.db.exists("Brand", brand):
                frappe.get_doc(doctype="Brand", brand=brand).insert(ignore_permissions=True)
            for name in frappe.get_all("Item", filters={ITEM_EXTERNAL_ID_FIELD: sku, "brand": ["is", "not set"]}, pluck="name"):
                frappe.db.set_value("Item", name, "brand", brand)
                filled += 1
        except Exception:
            failed += 1
            from alaiy_os_connector_unicommerce.unicommerce.log import log_once
            log_once(
                f"Unicommerce: could not refresh brand for {sku}",
                frappe.get_traceback(),
                key=f"brand-refresh:{sku}",
                window=24 * 60 * 60,
            )
    frappe.db.commit()
    return {"checked": len(pending), "filled": filled, "failed": failed}
