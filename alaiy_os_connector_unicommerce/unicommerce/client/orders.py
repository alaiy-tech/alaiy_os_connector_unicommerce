# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Sale order endpoints. Ref: https://documentation.unicommerce.com/"""

from frappe.utils import get_datetime
from pytz import timezone


def _utc_timeformat(value) -> str:
    """Datetime in UTC/GMT as required by Unicommerce."""
    return get_datetime(value).astimezone(timezone("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_sales_order(client, order_code: str):
    """https://documentation.unicommerce.com/docs/saleorder-get.html"""
    order, status = client.request(
        endpoint="/services/rest/v1/oms/saleorder/get", body={"code": order_code}
    )
    if status and "saleOrderDTO" in order:
        return order["saleOrderDTO"]


def search_sales_order(
    client,
    from_date: str | None = None,
    to_date: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    facility_codes: list[str] | None = None,
    updated_since: int | None = None,
):
    """https://documentation.unicommerce.com/docs/saleorder-search.html"""
    body = {
        "status": status,
        "channel": channel,
        "facilityCodes": facility_codes,
        "fromDate": _utc_timeformat(from_date) if from_date else None,
        "toDate": _utc_timeformat(to_date) if to_date else None,
        "updatedSinceInMinutes": updated_since,
    }
    body = {k: v for k, v in body.items() if v is not None}

    search_results, ok = client.request(endpoint="/services/rest/v1/oms/saleOrder/search", body=body)
    if ok and "elements" in search_results:
        return search_results["elements"]
