# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Item/catalog endpoints. Ref: https://documentation.unicommerce.com/"""


def get_unicommerce_item(client, sku: str, log_error=True):
    """https://documentation.unicommerce.com/docs/itemtype-get.html"""
    item, status = client.request(
        endpoint="/services/rest/v1/catalog/itemType/get", body={"skuCode": sku}, log_error=log_error
    )
    if status:
        return item


def search_item_types(client, display_start=0, display_length=100, category_code=None,
                      updated_since_hours=None, log_error=True):
    """
    One page of the tenant's catalogue.
    https://documentation.unicommerce.com/docs/search-itemtype.html

    Note the endpoint lives under /product/, not the /catalog/ prefix the
    get/createOrEdit calls use -- easy to miss when looking for a way to list
    items. Returns (elements, total_records); elements is [] on failure.
    """
    body = {
        "searchOptions": {
            "displayStart": display_start,
            "displayLength": display_length,
            "getCount": True,
        }
    }
    if category_code:
        body["categoryCode"] = category_code
    if updated_since_hours is not None:
        body["updatedSinceInHour"] = updated_since_hours

    res, ok = client.request(
        endpoint="/services/rest/v1/product/itemType/search", body=body, log_error=log_error)
    if not ok or not isinstance(res, dict):
        return [], 0
    return res.get("elements") or [], res.get("totalRecords") or 0


def create_update_item(client, item_dict: dict, update=False):
    """https://documentation.unicommerce.com/docs/createoredit-itemtype.html"""
    endpoint = "/services/rest/v1/catalog/itemType/createOrEdit"
    if update:
        # Edit has a separate endpoint even though the docs suggest otherwise.
        endpoint = "/services/rest/v1/catalog/itemType/edit"
    return client.request(endpoint=endpoint, body={"itemType": item_dict})
