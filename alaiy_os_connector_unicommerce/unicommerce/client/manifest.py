# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Shipping package + manifest endpoints. Ref: https://documentation.unicommerce.com/"""

from frappe.utils import cint

#: Matches `order.sync_old_orders`'s PAGE_SIZE for the sibling saleOrder/search
#: endpoint — same OMS search family, same `searchOptions` pagination shape.
SHIPPING_PACKAGE_PAGE_SIZE = 1000


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
    """https://documentation.unicommerce.com/docs/pos-shippingpackage-search.html

    Paginated. A single request without pagination silently returns only
    Unicommerce's own default page of results, newest first, no matter how
    wide `updated_since` is asked for -- confirmed live 2026-09-24, where a
    60-day window returned almost exactly the same packages a 7-day window
    already had, because both calls were really only ever seeing page one.
    Callers asking for a wide backlog window (`fulfillment.delivery_note`'s
    catch-up mode) would silently see only the most recent slice of it and
    have no way to tell the rest was never even requested.

    Walks pages with the same `searchOptions` shape `order.sync_old_orders`
    already uses successfully against the sibling saleOrder/search endpoint
    in this same OMS family, rather than inventing a new pagination
    convention for one endpoint.
    """
    base_body = {"statuses": statuses, "channelCode": channel, "updatedSinceInMinutes": updated_since}
    base_body = {k: v for k, v in base_body.items() if v is not None}

    display_start = 0
    total_records = None
    elements: list = []

    while True:
        body = dict(base_body)
        body["searchOptions"] = {
            "displayStart": display_start,
            "displayLength": SHIPPING_PACKAGE_PAGE_SIZE,
            "getCount": display_start == 0,
        }
        search_results, ok = client.request(
            endpoint="/services/rest/v1/oms/shippingPackage/search",
            body=body,
            headers={"Facility": facility_code},
        )
        if not ok or not search_results:
            break

        if display_start == 0:
            total_records = search_results.get("totalRecords")

        page = search_results.get("elements") or []
        if not page:
            break
        elements.extend(page)

        display_start += len(page)
        if total_records is not None and display_start >= total_records:
            break
        if len(page) < SHIPPING_PACKAGE_PAGE_SIZE:
            break

    return elements
