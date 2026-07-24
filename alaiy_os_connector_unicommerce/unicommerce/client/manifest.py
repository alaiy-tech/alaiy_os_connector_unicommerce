# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Shipping package + manifest endpoints. Ref: https://documentation.unicommerce.com/"""

from frappe.utils import cint


def update_shipping_package(
    client,
    shipping_package_code: str,
    facility_code: str,
    package_type_code: str,
    weight: int = 0,
    length: int = 0,
    width: int = 0,
    height: int = 0,
):
    """https://documentation.unicommerce.com/docs/shippingpackage-edit.html"""
    body = {
        "shippingPackageCode": shipping_package_code,
        "shippingPackageTypeCode": package_type_code,
    }

    def _positive(numbers):
        return all(cint(n) > 0 for n in numbers)

    if _positive([weight]):
        body["actualWeight"] = weight
    if _positive([length, width, height]):
        body["shippingBox"] = {"length": length, "width": width, "height": height}

    return client.request(
        endpoint="/services/rest/v1/oms/shippingPackage/edit",
        body=body,
        headers={"Facility": facility_code},
    )


def create_and_close_shipping_manifest(
    client,
    channel: str,
    shipping_provider_code: str,
    shipping_method_code: str,
    shipping_packages: list[str],
    facility_code: str,
    third_party_shipping: bool = True,
):
    """https://documentation.unicommerce.com/docs/pos-shippingmanifest-create-close.html"""
    body = {
        "channel": channel,
        "shippingProviderCode": shipping_provider_code,
        "shippingMethodCode": shipping_method_code,
        "thirdPartyShipping": third_party_shipping,
        "shippingPackageCodes": shipping_packages,
    }
    response, status = client.request(
        endpoint="/services/rest/v1/oms/shippingManifest/createclose",
        body=body,
        headers={"Facility": facility_code},
    )
    if status:
        return response


def get_shipping_manifest(client, shipping_manifest_code: str, facility_code: str):
    response, status = client.request(
        endpoint="/services/rest/v1/oms/shippingManifest/get",
        body={"shippingManifestCode": shipping_manifest_code},
        headers={"Facility": facility_code},
    )
    if status:
        return response


def search_shipping_packages(
    client,
    facility_code: str,
    channel: str | None = None,
    statuses: list[str] | None = None,
    updated_since: int | None = 6 * 60,
):
    """https://documentation.unicommerce.com/docs/pos-shippingpackage-search.html"""
    body = {"statuses": statuses, "channelCode": channel, "updatedSinceInMinutes": updated_since}
    body = {k: v for k, v in body.items() if v is not None}

    search_results, ok = client.request(
        endpoint="/services/rest/v1/oms/shippingPackage/search",
        body=body,
        headers={"Facility": facility_code},
    )
    if ok and "elements" in search_results:
        return search_results["elements"]
