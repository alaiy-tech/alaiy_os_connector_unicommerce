# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Customer + address creation from a Unicommerce order payload."""

import json
import re
from typing import Any

import frappe
from frappe.utils.nestedset import get_root_of

from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ADDRESS_JSON_FIELD, CUSTOMER_CODE_FIELD, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.geo import (
    UNICOMMERCE_COUNTRY_MAPPING, UNICOMMERCE_INDIAN_STATES_MAPPING,
)


# Amazon and Flipkart redact buyer name, address lines and phone at the API
# level, so those fields arrive as a run of asterisks rather than a value.
_MASKED_RE = re.compile(r"^\*+$")


def _is_masked(value) -> bool:
    return bool(value) and bool(_MASKED_RE.match(str(value).strip()))


def _customer_name(order: dict, address: dict) -> str:
    """Name to give a new Customer.

    Marketplace orders arrive with the buyer's name redacted to "********", so
    naming customers by it puts every single order under one name -- Frappe then
    appends " - N" and the counter collides once there are hundreds of them.
    Fall back to the order code, which keeps each anonymous buyer distinct and
    traceable back to Unicommerce. Channels that do send a real name (CUSTOM,
    for instance) keep using it.
    """
    name = (address.get("name") or "").strip()
    if name and not _is_masked(name):
        return name
    return f"{order['channel']} - {order.get('displayOrderCode') or order['code']}"


def sync_customer(order: dict):
    """Using the order payload, create a new customer if none matches yet.
    Note: Unicommerce itself doesn't deduplicate customers."""
    customer = _create_new_customer(order)
    _create_customer_addresses(order.get("addresses") or [], customer)
    return customer


def _create_new_customer(order: dict):
    address = order.get("billingAddress") or (order.get("addresses") and order.get("addresses")[0])
    address.pop("id", None)  # not important, can differ for the same physical address
    customer_code = order.get("customerCode")

    customer = _check_if_customer_exists(address, customer_code)
    if customer:
        return customer

    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    customer_group = (
        frappe.db.get_value("Unicommerce Channel", {"channel_id": order["channel"]}, "customer_group")
        or settings.default_customer_group
    )

    customer = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": _customer_name(order, address),
        "customer_group": customer_group,
        "territory": get_root_of("Territory"),
        "customer_type": "Individual",
        ADDRESS_JSON_FIELD: json.dumps(address),
        CUSTOMER_CODE_FIELD: customer_code,
    })
    customer.flags.ignore_mandatory = True
    customer.insert(ignore_permissions=True)
    return customer


def _check_if_customer_exists(address: dict, customer_code):
    """Crude match: if a customer code matches, or ALL address fields match
    an existing customer's stored raw address, reuse it instead of creating
    a duplicate."""
    customer_name = None
    if customer_code:
        customer_name = frappe.db.get_value("Customer", {CUSTOMER_CODE_FIELD: customer_code})

    # A redacted address cannot identify a person: name, address lines and phone
    # are all asterisks, leaving only city/state/pincode. Matching on it would
    # merge every masked buyer in the same pincode into one customer, so a
    # marketplace order without a customer code always gets its own record.
    if not customer_name and not _is_masked(address.get("name")):
        customer_name = frappe.db.get_value("Customer", {ADDRESS_JSON_FIELD: json.dumps(address)})

    if customer_name:
        return frappe.get_doc("Customer", customer_name)


def _create_customer_addresses(addresses: list, customer) -> None:
    """Unicommerce orders carry an address list: one address means it's both
    billing and shipping; two or more means the first is billing, second is
    shipping."""
    if len(addresses) == 1:
        _create_customer_address(addresses[0], "Billing", customer, also_shipping=True)
    elif len(addresses) >= 2:
        _create_customer_address(addresses[0], "Billing", customer)
        _create_customer_address(addresses[1], "Shipping", customer)


def _create_customer_address(uni_address: dict, address_type: str, customer, also_shipping: bool = False):
    country_code = uni_address.get("country")
    country = UNICOMMERCE_COUNTRY_MAPPING.get(country_code)

    state = uni_address.get("state")
    if country_code == "IN" and state in UNICOMMERCE_INDIAN_STATES_MAPPING:
        state = UNICOMMERCE_INDIAN_STATES_MAPPING.get(state)

    frappe.get_doc({
        "address_line1": uni_address.get("addressLine1") or "Not provided",
        "address_line2": uni_address.get("addressLine2"),
        "address_type": address_type,
        "city": uni_address.get("city"),
        "country": country,
        "county": uni_address.get("district"),
        "doctype": "Address",
        "email_id": uni_address.get("email"),
        "phone": uni_address.get("phone"),
        "pincode": uni_address.get("pincode"),
        "state": state,
        "links": [{"link_doctype": "Customer", "link_name": customer.name}],
        "is_primary_address": int(address_type == "Billing"),
        "is_shipping_address": int(also_shipping or address_type == "Shipping"),
        # ERPNext core's Address.validate() (accounts/custom/address.py)
        # reads self.is_your_company_address unconditionally -- on a site
        # where that field is genuinely absent from the doctype (confirmed
        # live: frappe.get_meta("Address").get_field(...) returns None even
        # after a fresh migrate), accessing it raises AttributeError instead
        # of reading as falsy, crashing every single order's address
        # creation. This is a customer's own address, never the company's,
        # so 0 is also the semantically correct value here, not just a
        # workaround for the missing field.
        "is_your_company_address": 0,
    }).insert(ignore_mandatory=True)


def check_customer_naming():
    """Self-check for the masked-buyer naming rules. No DB access.

    bench --site <site> execute \
        alaiy_os_connector_unicommerce.unicommerce.customer.check_customer_naming
    """
    assert _is_masked("********")
    assert _is_masked("  ****  ")
    assert not _is_masked("Anas Ahmed")
    assert not _is_masked("")
    assert not _is_masked(None)
    # A partially redacted value is still real data -- don't treat it as masked.
    assert not _is_masked("A*** A****")

    order = {"channel": "FLIPKART_GLOBALI", "code": "565f2969", "displayOrderCode": "OD4381377550"}

    # Masked and empty names both fall back to the order code, and two orders
    # from different anonymous buyers must not collide.
    assert _customer_name(order, {"name": "********"}) == "FLIPKART_GLOBALI - OD4381377550"
    assert _customer_name(order, {"name": ""}) == "FLIPKART_GLOBALI - OD4381377550"
    assert _customer_name(order, {}) == "FLIPKART_GLOBALI - OD4381377550"
    other = dict(order, displayOrderCode="OD9999999999")
    assert _customer_name(order, {"name": "********"}) != _customer_name(other, {"name": "********"})

    # displayOrderCode is preferred, but the internal code is a valid fallback.
    assert _customer_name({"channel": "CUSTOM", "code": "abc123"}, {"name": "********"}) == "CUSTOM - abc123"

    # A real name is kept, whitespace trimmed.
    assert _customer_name(order, {"name": "Anas Ahmed"}) == "Anas Ahmed"
    assert _customer_name(order, {"name": "  Anas Ahmed  "}) == "Anas Ahmed"

    print("customer naming self-check passed")
