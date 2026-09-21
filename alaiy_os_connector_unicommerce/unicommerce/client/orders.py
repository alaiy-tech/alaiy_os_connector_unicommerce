# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Sale order endpoints. Ref: https://documentation.unicommerce.com/"""

from frappe.utils import get_datetime, get_system_timezone
from pytz import timezone

UTC = timezone("UTC")


def _to_utc(value):
    """Naive site-local datetime -> tz-aware UTC.

    The naive datetimes this connector passes around (now_datetime(),
    last_po_sync, ...) are in the SITE's timezone, which is not necessarily
    the machine's. `.astimezone()` on a naive value silently assumes the OS
    timezone, so on a UTC host running an Asia/Kolkata site it converted
    nothing at all and stamped IST wall-clock time with a "Z" -- every
    absolute window sent to Unicommerce landed 5:30 in the future.

    Retail order sync never noticed: it filters on `updatedSinceInMinutes`,
    which is relative. B2B never noticed either -- its window is 30 days
    wide, so losing 5.5h off one end changes nothing. The purchase order and
    inflow-receipt searches did: their incremental window is minutes wide,
    so all of it sat in dead future space and matched zero rows on every
    run. Confirmed live as Fill Rate stuck at 0% with no error anywhere,
    because "no results" is not a failure.

    Localising against the site timezone explicitly stops the host's own
    setting from mattering.
    """
    dt = get_datetime(value)
    if dt.tzinfo is None:
        dt = timezone(get_system_timezone()).localize(dt)
    return dt.astimezone(UTC)


def _utc_timeformat(value) -> str:
    """Datetime in UTC/GMT as required by Unicommerce."""
    return _to_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_sales_order(client, order_code: str):
    """https://documentation.unicommerce.com/docs/saleorder-get.html"""
    order, status = client.request(
        endpoint="/services/rest/v1/oms/saleorder/get", body={"code": order_code}
    )
    if status and "saleOrderDTO" in order:
        return order["saleOrderDTO"]


def get_return(client, facility_code: str, shipment_code: str | None = None,
               reverse_pickup_code: str | None = None):
    """Return detail for one shipment or reverse pickup.

    https://documentation.unicommerce.com/docs/return-get.html

    saleorder/get's own `returns` list carries only enough to tell RTO from a
    customer return; the reason, courier and pickup address live here and
    nowhere else. Needs one of shipmentCode / reversePickupCode -- Unicommerce
    rejects a call with neither.
    """
    if not (shipment_code or reverse_pickup_code):
        return None

    response, status = client.request(
        endpoint="/services/rest/v1/oms/return/get",
        body={"shipmentCode": shipment_code, "reversePickupCode": reverse_pickup_code},
        headers={"Facility": facility_code},
    )
    if status:
        return response


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
