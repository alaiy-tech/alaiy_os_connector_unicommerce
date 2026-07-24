# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Item <-> Unicommerce itemType field mapping.
Ref: https://documentation.unicommerce.com/docs/itemtype-get.html
"""

from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ITEM_BATCH_GROUP_FIELD, ITEM_HEIGHT_FIELD, ITEM_LENGTH_FIELD, ITEM_WIDTH_FIELD,
)

UNI_TO_ITEM_FIELD = {
    "skuCode": "item_code",
    "name": "item_name",
    "description": "description",
    "weight": "weight_per_unit",  # weight_uom is always grams
    "brand": "brand",
    "shelfLife": "shelf_life_in_days",
    "hsnCode": "gst_hsn_code",
    "imageUrl": "image",
    "length": ITEM_LENGTH_FIELD,
    "width": ITEM_WIDTH_FIELD,
    "height": ITEM_HEIGHT_FIELD,
    "batchGroupCode": ITEM_BATCH_GROUP_FIELD,
    "maxRetailPrice": "standard_rate",
    "costPrice": "valuation_rate",
}

ITEM_FIELD_TO_UNI = {v: k for k, v in UNI_TO_ITEM_FIELD.items()}
