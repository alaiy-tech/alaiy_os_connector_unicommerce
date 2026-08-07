# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Purchase order endpoints. Ref: https://documentation.unicommerce.com/

REST, not SOAP -- same as every other endpoint this connector calls (see
client/core.py's docstring). Unicommerce's PO search has no pagination of
its own: getPurchaseOrders returns every matching PO code in one response,
capped only by the date-range filter, both ends of which are mandatory.
"""

from alaiy_os_connector_unicommerce.unicommerce.client.orders import _utc_timeformat


def search_purchase_orders(client, created_from, created_to, approved_from=None, approved_to=None):
    """https://documentation.unicommerce.com/docs/purchaseorder_search.html

    approvedBetween is mandatory on this endpoint even though createdBetween
    is the one we actually use for incremental sync -- default it to the
    same window when not given so callers don't have to think about it.
    """
    body = {
        "createdBetween": {
            "start": _utc_timeformat(created_from),
            "end": _utc_timeformat(created_to),
        },
        "approvedBetween": {
            "start": _utc_timeformat(approved_from or created_from),
            "end": _utc_timeformat(approved_to or created_to),
        },
    }
    result, ok = client.request(endpoint="/services/rest/v1/purchase/purchaseOrder/getPurchaseOrders", body=body)
    if ok and "purchaseOrderCodes" in result:
        return result["purchaseOrderCodes"]


def get_purchase_order_details(client, po_code: str, facility_code: str | None = None):
    """https://documentation.unicommerce.com/docs/get_purchase_order_details.html

    Facility-level endpoint -- Unicommerce scopes this call by the Facility
    header, not a body field (the response itself carries no facility code
    at all). facility_code is passed straight through as that header;
    caller is responsible for knowing which facility to ask for."""
    headers = {"Facility": facility_code} if facility_code else None
    result, ok = client.request(
        endpoint="/services/rest/v1/purchase/purchaseOrder/getPurchaseOrderDetails",
        body={"purchaseOrderCode": po_code},
        headers=headers,
    )
    if ok and result.get("code"):
        return result


def search_inflow_receipts(client, created_from, created_to, facility_code: str, po_code: str | None = None):
    """https://documentation.unicommerce.com/docs/inflowreceipt-getinflowreceipts.html
    Facility-level, same Facility-header scoping as PO details."""
    body = {
        "createdBetween": {
            "start": _utc_timeformat(created_from),
            "end": _utc_timeformat(created_to),
        },
    }
    if po_code:
        body["purchaseOrderCode"] = po_code
    result, ok = client.request(
        endpoint="/services/rest/v1/purchase/inflowReceipt/getInflowReceipts",
        body=body,
        headers={"Facility": facility_code},
    )
    if ok and "inflowReceiptCodes" in result:
        return result["inflowReceiptCodes"]


def get_inflow_receipt(client, receipt_code: str, facility_code: str):
    """https://documentation.unicommerce.com/docs/inflowreceipt-getinflowreceipt.html"""
    result, ok = client.request(
        endpoint="/services/rest/v1/purchase/inflowReceipt/getInflowReceipt",
        body={"inflowReceiptCode": receipt_code},
        headers={"Facility": facility_code},
    )
    if ok and result.get("inflowReceipt"):
        return result["inflowReceipt"]
