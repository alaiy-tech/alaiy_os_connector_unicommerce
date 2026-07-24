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


def create_update_item(client, item_dict: dict, update=False):
    """https://documentation.unicommerce.com/docs/createoredit-itemtype.html"""
    endpoint = "/services/rest/v1/catalog/itemType/createOrEdit"
    if update:
        # Edit has a separate endpoint even though the docs suggest otherwise.
        endpoint = "/services/rest/v1/catalog/itemType/edit"
    return client.request(endpoint=endpoint, body={"itemType": item_dict})
