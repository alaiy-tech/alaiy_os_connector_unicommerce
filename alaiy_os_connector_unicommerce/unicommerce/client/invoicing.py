# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Invoice/label endpoints. Ref: https://documentation.unicommerce.com/"""

import base64


def create_sales_invoice(client, so_code: str, so_item_codes: list[str], facility_code: str):
    body = {"saleOrderCode": so_code, "saleOrderItemCodes": so_item_codes}
    response, _status = client.request(
        endpoint="/services/rest/v1/invoice/createInvoiceBySaleOrderCode",
        body=body,
        headers={"Facility": facility_code},
    )
    return response


def create_invoice_by_shipping_code(client, shipping_package_code: str, facility_code: str):
    response, _status = client.request(
        endpoint="/services/rest/v1/oms/shippingPackage/createInvoice",
        body={"shippingPackageCode": shipping_package_code},
        headers={"Facility": facility_code},
    )
    return response


def create_invoice_and_assign_shipper(client, shipping_package_code: str, facility_code: str):
    """Invoice + label generation for self-shipped orders.
    https://documentation.unicommerce.com/docs/pos-shippingpackage-createinvoice-allocateshippingprovider.html
    """
    response, _status = client.request(
        endpoint="/services/rest/v1/oms/shippingPackage/createInvoiceAndAllocateShippingProvider",
        body={"shippingPackageCode": shipping_package_code},
        headers={"Facility": facility_code},
    )
    return response


def create_invoice_and_label_by_shipping_code(
    client, shipping_package_code: str, facility_code: str, generate_label: bool = True
):
    """Invoice + label generation for marketplace orders.
    https://documentation.unicommerce.com/docs/create_invoiceandlabel_by_shippingpackagecode.html
    """
    response, _status = client.request(
        endpoint="/services/rest/v1/oms/shippingPackage/createInvoiceAndGenerateLabel",
        body={"shippingPackageCode": shipping_package_code, "generateUniwareShippingLabel": generate_label},
        headers={"Facility": facility_code},
    )
    return response


def get_sales_invoice(client, shipping_package_code: str, facility_code: str, is_return: bool = False):
    """https://documentation.unicommerce.com/docs/invoice-getdetails.html"""
    response, status = client.request(
        endpoint="/services/rest/v1/invoice/details/get",
        body={"shippingPackageCode": shipping_package_code, "return": is_return},
        headers={"Facility": facility_code},
    )
    if status:
        return response


def get_invoice_label(client, shipping_package_code: str, facility_code: str):
    """Get the generated label for a given shipping package. Undocumented."""
    pdf, status = client.request(
        endpoint="/services/rest/v1/oms/shipment/show",
        method="GET",
        params={"shippingPackageCodes": shipping_package_code},
        headers={"Facility": facility_code},
    )
    if status and pdf:
        return base64.b64encode(pdf)
