# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Sale order endpoints. Ref: https://documentation.unicommerce.com/"""

import frappe
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


#: Matches `order.sync_old_orders`'s PAGE_SIZE for this same endpoint.
SALE_ORDER_SEARCH_PAGE_SIZE = 1000


def search_sales_order(
    client,
    from_date: str | None = None,
    to_date: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    facility_codes: list[str] | None = None,
    updated_since: int | None = None,
):
    """https://documentation.unicommerce.com/docs/saleorder-search.html

    Paginated. A single request without pagination silently returns only
    Unicommerce's own default page of results no matter how wide a window is
    asked for -- confirmed live 2026-09-28: `order.pull._get_new_orders`
    calls this once a day asking for everything updated in the last 24
    hours, and on any day with more updates than one page holds, everything
    past page one was silently dropped. Worse than a one-off miss: the NEXT
    day's run only looks back 24 hours from then, so an order that fell off
    today's page is never inside any future run's window either -- it is
    gone for good, not just late. Traced to ~2,940 real Flipkart orders
    across Jul-Aug 2026 with no Sales Order at all, surfaced downstream as
    "Missing invoice" settlement findings months later with no indication
    the actual cause was here.

    Walks pages with the same `searchOptions` shape `order.sync_old_orders`
    already uses successfully against this identical endpoint, rather than
    inventing a new pagination convention for the routine sync path.

    Returns `None` if the FIRST page fails -- `order.pull._get_new_orders`
    distinguishes that from a genuinely empty result (a quiet window) and
    logs it as a failed run rather than silently importing nothing. A LATER
    page failing mid-walk returns whatever was already fetched instead,
    logged as incomplete: the orders on those earlier pages are real and
    already safe to import, and discarding them on a later page's failure
    would be strictly worse than what this function used to do.
    """
    base_body = {
        "status": status,
        "channel": channel,
        "facilityCodes": facility_codes,
        "fromDate": _utc_timeformat(from_date) if from_date else None,
        "toDate": _utc_timeformat(to_date) if to_date else None,
        "updatedSinceInMinutes": updated_since,
    }
    base_body = {k: v for k, v in base_body.items() if v is not None}

    display_start = 0
    total_records = None
    elements: list = []

    while True:
        body = dict(base_body)
        body["searchOptions"] = {
            "displayStart": display_start,
            "displayLength": SALE_ORDER_SEARCH_PAGE_SIZE,
            "getCount": display_start == 0,
        }
        search_results, ok = client.request(endpoint="/services/rest/v1/oms/saleOrder/search", body=body)
        if not ok or not search_results:
            if display_start == 0:
                return None
            frappe.log_error(
                title="Unicommerce: sale order search failed mid-page",
                message=(
                    f"Search FAILED at displayStart={display_start}. Returning the "
                    f"{len(elements):,} orders already fetched on earlier pages rather than "
                    "discarding them -- re-run the same window to pick up the rest."
                ),
            )
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
        if len(page) < SALE_ORDER_SEARCH_PAGE_SIZE:
            break

    return elements
