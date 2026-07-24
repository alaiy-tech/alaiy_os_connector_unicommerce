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
