# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Push shipping-package changes (package type -> dimensions) back to Unicommerce."""

import json

import frappe

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.client.manifest import update_shipping_package
from alaiy_os_connector_unicommerce.unicommerce.constants import FACILITY_CODE_FIELD, ORDER_CODE_FIELD, PACKAGE_TYPE_FIELD


def update_shipping_info(doc, method=None):
    """Sales Order on_update_after_submit: when the package type changes,
    push the new dimensions to Unicommerce."""
    so = doc
    if not so.has_value_changed(PACKAGE_TYPE_FIELD):
        return
    if not so.get(PACKAGE_TYPE_FIELD):
        return
    frappe.enqueue(_update_package_info_on_unicommerce, queue="short", so_code=so.name)


def _update_package_info_on_unicommerce(so_code: str):
    try:
        client = UnicommerceClient()
        so = frappe.get_doc("Sales Order", so_code)
        package_info = frappe.get_doc("Unicommerce Package Type", so.get(PACKAGE_TYPE_FIELD))

        updated_so_data = get_sales_order(client, so.get(ORDER_CODE_FIELD))
        shipping_packages = (updated_so_data or {}).get("shippingPackages")
        if not shipping_packages:
            frappe.throw(frappe._("Shipping package not present on Unicommerce for order {0}").format(so.name))

        response, status = update_shipping_package(
            client,
            shipping_package_code=shipping_packages[0].get("code"),
            facility_code=so.get(FACILITY_CODE_FIELD),
            package_type_code=package_info.package_type_code or "DEFAULT",
            length=package_info.length,
            width=package_info.width,
            height=package_info.height,
        )
        if not status:
            so.add_comment(
                text="Unicommerce integration: could not update package size\n"
                + json.dumps((response or {}).get("errors"), indent=4)
            )
    except Exception:
        frappe.log_error(
            title=f"Unicommerce: failed to update shipping package for {so_code}",
            message=frappe.get_traceback(),
        )
        raise
