# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Self-check for apply_return_details()'s parsing of /oms/return/get.

Runs standalone (no frappe, no site):

    python unicommerce/order/test_return_details.py

Shapes below are taken from the documented response payload
(docs/unicommerce-docs/client/returns/return-get.md): returnSaleOrderValue
carries rtoReason/courier, returnSaleOrderItems carries the marketplace
reason, and the pincode is on the PICKUP row of returnAddressDetailsList.
"""


class _Doc(dict):
    """Stand-in for a Frappe doc -- only .set/.get are used."""
    def set(self, k, v):
        self[k] = v
    def get(self, k, default=None):
        return dict.get(self, k, default)


def _parse(detail):
    """The body of apply_return_details() after the fetch, verbatim in shape."""
    values = detail.get("returnSaleOrderValue") or []
    value = values[0] if isinstance(values, list) and values else (values if isinstance(values, dict) else {})

    items = detail.get("returnSaleOrderItems") or []
    item = items[0] if isinstance(items, list) and items else (items if isinstance(items, dict) else {})

    reason = (value.get("rtoReason") or item.get("marketplaceReturnReason")
              or item.get("returnRemarks") or item.get("trackingStatus")
              or item.get("courierStatus"))
    courier = (value.get("rtoCourierName") or value.get("courierName")
               or value.get("rtoShippingProviderCode") or value.get("shippingProviderCode"))

    addresses = detail.get("returnAddressDetailsList") or []
    pickup = (next((a for a in addresses if a.get("type") == "PICKUP"), None)
              or next((a for a in addresses if a.get("type") == "SHIPPING"), None)
              or (addresses[0] if addresses else {}))
    return reason, courier, pickup.get("pincode")


def demo():
    # RTO: reason and courier on returnSaleOrderValue.
    reason, courier, pin = _parse({
        "returnSaleOrderValue": [{"rtoReason": "Customer not available",
                                  "rtoCourierName": "Delhivery", "courierName": "Ignored"}],
        "returnAddressDetailsList": [{"type": "BILLING", "pincode": "110001"},
                                     {"type": "PICKUP", "pincode": "560034"}],
    })
    assert reason == "Customer not available", reason
    assert courier == "Delhivery", courier
    assert pin == "560034", f"must prefer the PICKUP row, got {pin}"

    # Customer return: no rtoReason, so the marketplace reason on the item wins.
    reason, courier, pin = _parse({
        "returnSaleOrderValue": [{"rtoReason": None, "courierName": "BlueDart"}],
        "returnSaleOrderItems": [{"marketplaceReturnReason": "Size & fit"}],
        "returnAddressDetailsList": [{"type": "PICKUP", "pincode": "400001"}],
    })
    assert reason == "Size & fit", reason
    assert courier == "BlueDart", "falls back to courierName when there is no RTO courier"
    assert pin == "400001"

    # returnRemarks is the last resort when neither reason field is set.
    reason, _, _ = _parse({"returnSaleOrderItems": [{"returnRemarks": "Damaged in transit"}]})
    assert reason == "Damaged in transit", reason

    # No PICKUP row -> fall back to the first address rather than dropping it.
    _, _, pin = _parse({"returnAddressDetailsList": [{"type": "SHIPPING", "pincode": "700001"}]})
    assert pin == "700001", pin

    # Every field absent must parse to None, never raise -- a partial payload
    # must not break a credit note that is otherwise correct.
    assert _parse({}) == (None, None, None)
    assert _parse({"returnSaleOrderValue": [], "returnAddressDetailsList": []}) == (None, None, None)

    # Docs type these as lists, but tolerate a bare object.
    reason, _, _ = _parse({"returnSaleOrderValue": {"rtoReason": "Refused"}})
    assert reason == "Refused", reason

    # A REAL Flipkart RTO payload (globali, package GLOB07305, 1 Sep 2026).
    # Every documented reason field and both courier-name fields are null --
    # this shape is why the trackingStatus/shippingProviderCode fallbacks and
    # the SHIPPING address tier exist. Docs alone would have shipped three
    # permanently empty fields.
    reason, courier, pin = _parse({
        "returnSaleOrderItems": [{
            "marketplaceReturnReason": None, "returnRemarks": None,
            "courierStatus": "COURIER_RETURN-DELIVERED",
            "trackingStatus": "RTO_DELIVERED_TO_SELLER",
        }],
        # NOTE: a bare dict here, though the docs type it as a list.
        "returnSaleOrderValue": {
            "rtoReason": None, "rtoCourierName": None, "courierName": None,
            "rtoShippingProviderCode": "E-Kart Logistics",
            "shippingProviderCode": "E-Kart Logistics",
        },
        "returnAddressDetailsList": [
            {"type": "SHIPPING", "pincode": "281306"},
            {"type": "BILLING", "pincode": "281306"},
        ],
    })
    assert reason == "RTO_DELIVERED_TO_SELLER", f"live RTO must fall back to tracking status, got {reason}"
    assert courier == "E-Kart Logistics", f"live RTO must fall back to provider code, got {courier}"
    assert pin == "281306", pin

    # BILLING must never win over SHIPPING when both are present.
    _, _, pin = _parse({"returnAddressDetailsList": [
        {"type": "BILLING", "pincode": "111111"}, {"type": "SHIPPING", "pincode": "222222"}]})
    assert pin == "222222", f"SHIPPING must beat BILLING, got {pin}"

    print("OK: reason/courier precedence incl. live-RTO fallbacks, address tiers, empty payloads, dict-or-list")


if __name__ == "__main__":
    demo()
