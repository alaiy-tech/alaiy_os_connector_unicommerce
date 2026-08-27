# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Inventory endpoints. Ref: https://documentation.unicommerce.com/"""

from alaiy_os_connector_unicommerce.unicommerce.log import log_api_error


def get_inventory_snapshot(client, sku_codes: list[str], facility_code: str, updated_since: int = 1430):
    """https://documentation.unicommerce.com/docs/inventory-snapshot.html"""
    response, status = client.request(
        endpoint="/services/rest/v1/inventory/inventorySnapshot/get",
        headers={"Facility": facility_code},
        body={"itemTypeSKUs": sku_codes, "updatedSinceInMinutes": updated_since},
    )
    if status:
        return response


def search_itemtype_with_inventory(
    client, facility_code: str, display_start: int = 0, display_length: int = 500,
    category_code: str | None = None,
):
    """https://documentation.unicommerce.com/docs/search-itemtype.html

    Unlike get_inventory_snapshot (which only returns SKUs updated within the
    last 24 hours -- confirmed live, Unicommerce rejects any wider window
    with "You can query for only one day snapshots"), this is a real paged
    catalogue search with getInventorySnapshot=true, so it returns current
    stock for every item regardless of when it last changed. Needed for a
    full baseline pull -- an item with no recent order activity has nothing
    for the snapshot endpoint to report, which is why brands with a long
    tail of slow-moving SKUs never got an initial Bin row at all.
    """
    response, status = client.request(
        endpoint="/services/rest/v1/product/itemType/search",
        headers={"Facility": facility_code},
        body={
            "categoryCode": category_code,
            "getInventorySnapshot": True,
            "searchOptions": {
                "displayStart": display_start,
                "displayLength": display_length,
                "getCount": True,
            },
        },
    )
    if status:
        return response


def bulk_inventory_update(client, facility_code: str, inventory_map: dict[str, int]):
    """Bulk update inventory on Unicommerce using SKU and qty (qty is the
    "total" quantity, not a delta).
    https://documentation.unicommerce.com/docs/adjust-inventory-bulk.html
    """
    inventory_adjustments = [
        {
            "itemSKU": sku,
            "quantity": qty,
            "shelfCode": "DEFAULT",
            "inventoryType": "GOOD_INVENTORY",
            "adjustmentType": "REPLACE",
            "facilityCode": facility_code,
        }
        for sku, qty in inventory_map.items()
    ]

    response, status = client.request(
        endpoint="/services/rest/v1/inventory/adjust/bulk",
        headers={"Facility": facility_code},
        body={"inventoryAdjustments": inventory_adjustments},
    )
    if not status:
        return response, status

    try:
        item_wise_response = response["inventoryAdjustmentResponses"]
        item_wise_status = {
            item["facilityInventoryAdjustment"]["itemSKU"]: item["successful"]
            for item in item_wise_response
        }
        if False in item_wise_status.values():
            log_api_error("Unicommerce: inventory sync failed for some items", response_data=response)
        return item_wise_status, status
    except Exception:
        return response, False
