# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Unicommerce B2B sale orders -> Alaiy OS.

B2B orders are invisible to the ordinary order sync, and not because of a
filter we control. `/oms/saleOrder/search` -- the endpoint `order/pull.py`
discovers retail orders with -- returns nothing for them under any
parameters: not by channel, not by `displayOrderCode`, not by date window,
and Unicommerce rejects `saleOrderType`/`b2b` as unknown fields outright.
`/oms/saleorder/get` fetches one happily once you already know its code.

So the connector could always READ a B2B order and never LEARN that one
existed. On the Globali tenant that meant every Flipkart Minutes PO -- 155
orders and 192,470 units at the time of writing -- was absent from the
site, while the team ran replenishment off a spreadsheet holding 48 of them.

Discovery therefore goes through Unicommerce's export-job API, which is the
only route that lists them. It is asynchronous by nature (create a job,
poll, download a CSV), which is why this is a separate module rather than
another branch inside `order/pull.py`: the retail path is a synchronous
search and stays that way.

Once the codes are known, everything rejoins the existing pipeline --
`get_sales_order` then `create_order` -- so B2B orders get the same
customer, tax, warehouse and item handling as every other order.
"""

import csv
import io
import time

import frappe
import requests
from frappe.utils import add_to_date, now_datetime

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.orders import _to_utc, get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.channel_discovery import (
    discover_channels, get_configured_channels,
)
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    ORDER_CODE_FIELD, ORDER_STATUS_FIELD, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.order.cancellation import fully_cancel_orders
from alaiy_os_connector_unicommerce.unicommerce.order.pull import create_order

#: The export config that lists B2B orders. Confirmed against the live
#: tenant: `type: EXPORT`, access resource `EXPORT_SALE_ORDERS`. The full
#: catalogue of names is readable at /data/tasks/export/configs.
EXPORT_JOB_TYPE = "B2B Sale Orders"

#: Unicommerce's own spelling. Not a typo on our side -- the API field is
#: `exportColums`, and sending `exportColumns` is rejected as missing.
EXPORT_COLUMNS = [
    "saleOrderCode", "displayorderCode", "channel", "status",
    "displayOrderDateTime", "skuCode", "channelProductId",
    "soiTotalQty", "sellingPrice", "maxRetailPrice", "facility",
]

#: At least one filter carrying `eitherOrTag` "1" is mandatory; the export
#: config offers `addedOn` and `updatedOn`, both date ranges. `addedOn` is
#: used so a re-run covers the same set deterministically -- `updatedOn`
#: would let an order drift out of the window simply by being touched.
EXPORT_FILTER_ID = "addedOn"

_POLL_INTERVAL_SECONDS = 5
_POLL_TIMEOUT_SECONDS = 300
_DOWNLOAD_TIMEOUT_SECONDS = 120

#: Lookback for a scheduled run. Generous on purpose: an order that fails to
#: import must still be in range on the next attempt, and the codes we have
#: already stored are skipped before any per-order fetch, so overlap is cheap.
DEFAULT_LOOKBACK_DAYS = 30

#: Once a B2B order's own status moves outside this set, Unicommerce has
#: made a final call on it -- moving through fulfilment, or rejected -- and
#: there is nothing left to learn by asking again. Anything still in one of
#: these is provisional: Flipkart can still reject or amend the PO, yet
#: `create_order` submits it as final revenue the instant it is first
#: discovered, and until now nothing ever asked Unicommerce about a known
#: order code a second time (`_already_imported` skipped it for good).
#:
#: Confirmed live 2026-09-28: a single Flipkart Minutes PO worth ~10.3L,
#: over half that day's B2B revenue, was still PENDING_VERIFICATION on
#: Unicommerce while sitting fully submitted here -- Unicommerce's own
#: revenue-by-channel widget, which apparently only counts confirmed
#: business orders, read ~7.9L lower than ours for the identical day as a
#: direct result. `_reconcile_pending` below closes that gap for the one
#: unambiguous case (Unicommerce rejects the PO outright); an amendment to
#: quantity/price on an already-submitted order is a separate, riskier
#: problem this deliberately does not attempt.
_PENDING_B2B_STATUSES = {"PENDING_VERIFICATION"}


def sync_b2b_orders(client: UnicommerceClient = None, force: bool = False, lookback_days: int = None):
    """Discover B2B orders via an export job and import the new ones."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled or not settings.get("sync_b2b_orders"):
        return

    if client is None:
        client = UnicommerceClient()

    days = lookback_days or DEFAULT_LOOKBACK_DAYS
    rows = _export_rows(client, since=add_to_date(now_datetime(), days=-days))
    if rows is None:
        return

    discovered = {r["channel"] for r in rows if r.get("channel")}
    discover_channels(discovered)
    configured = get_configured_channels()

    # Deliberately the same gate the retail path applies: a channel nobody has
    # enabled locally is not silently imported just because it arrived by a
    # different route.
    codes = {
        r["code"] for r in rows
        if r.get("code") and r.get("channel") in configured
    }
    if not codes:
        return

    already = _already_imported(codes)
    for code in sorted(codes - already):
        try:
            payload = get_sales_order(client, code)
            if payload:
                create_order(payload, client=client)
        except Exception:
            # One malformed order must not abandon the rest of the batch --
            # a B2B run covers a month of POs, not a single order.
            frappe.log_error(title=f"Unicommerce B2B: import failed for {code}")

    # `already` is bounded by the same "addedOn" export window as `codes`
    # itself (see EXPORT_FILTER_ID's docstring) -- exactly the set worth
    # re-asking Unicommerce about, at the same cadence as new discovery,
    # with no extra API call needed to find them.
    _reconcile_pending(already, client)

    frappe.db.set_value(
        SETTINGS_DOCTYPE, None, "last_b2b_sync", now_datetime(), update_modified=False
    )


def _reconcile_pending(codes: set[str], client: UnicommerceClient) -> None:
    """Re-check already-imported B2B orders still sitting in a provisional
    status, and cancel the ones Unicommerce has since rejected.

    Deliberately narrow. A flip to CANCELLED is unambiguous and already has
    a safe, established path (`fully_cancel_orders`, which refuses to touch
    an order that already has a Sales Invoice against it). An amendment to a
    still-pending order's quantity or price is a different, harder problem
    -- cancelling and recreating an already-submitted document -- and is
    deliberately left alone here rather than attempted as a silent
    background correction.
    """
    if not codes:
        return

    pending_locally = frappe.get_all(
        "Sales Order",
        filters={
            ORDER_CODE_FIELD: ("in", list(codes)),
            ORDER_STATUS_FIELD: ("in", list(_PENDING_B2B_STATUSES)),
            "docstatus": 1,
        },
        pluck=ORDER_CODE_FIELD,
    )
    if not pending_locally:
        return

    now_cancelled = []
    for code in pending_locally:
        try:
            payload = get_sales_order(client, code)
        except Exception:
            frappe.log_error(title=f"Unicommerce B2B: status re-check failed for {code}")
            continue
        if not payload:
            continue

        live_status = payload.get("status")
        if live_status == "CANCELLED":
            now_cancelled.append(code)
        elif live_status and live_status not in _PENDING_B2B_STATUSES:
            # Moved on to a confirmed/processing state -- nothing to cancel,
            # just stop calling it provisional so it drops out of this check
            # on the next run instead of being re-fetched forever.
            frappe.db.set_value(
                "Sales Order", {ORDER_CODE_FIELD: code}, ORDER_STATUS_FIELD, live_status,
                update_modified=False,
            )

    if now_cancelled:
        fully_cancel_orders(now_cancelled)


def _already_imported(codes: set[str]) -> set[str]:
    if not codes:
        return set()
    return set(
        frappe.get_all(
            "Sales Order",
            filters={ORDER_CODE_FIELD: ("in", list(codes))},
            pluck=ORDER_CODE_FIELD,
            limit_page_length=0,
        )
    )


def _export_rows(client: UnicommerceClient, since) -> list[dict] | None:
    """Create the export job, wait for it, and return its parsed rows."""
    job_code = _create_export_job(client, since)
    if not job_code:
        return None

    file_url = _await_export(client, job_code)
    if not file_url:
        return None

    return _download_rows(file_url)


def _create_export_job(client: UnicommerceClient, since) -> str | None:
    body = {
        "exportJobTypeName": EXPORT_JOB_TYPE,
        "exportColums": EXPORT_COLUMNS,
        "frequency": "ONETIME",
        "exportFilters": [{
            "id": EXPORT_FILTER_ID,
            "dateRange": {
                "start": _as_utc(since),
                "end": _as_utc(now_datetime()),
            },
        }],
    }
    response, ok = client.request(
        "/services/rest/v1/export/job/create", headers=_facility_header(), body=body
    )
    if not ok or not response:
        frappe.log_error(
            title="Unicommerce B2B: could not create export job",
            message=str(response),
        )
        return None
    return response.get("jobCode")


def _await_export(client: UnicommerceClient, job_code: str) -> str | None:
    """Poll until the job finishes. Returns the CSV url, or None on timeout."""
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response, ok = client.request(
            "/services/rest/v1/export/job/status",
            headers=_facility_header(),
            body={"jobCode": job_code},
        )
        if ok and response and response.get("status") == "COMPLETE":
            return response.get("filePath")
        if ok and response and response.get("status") in ("FAILED", "CANCELLED"):
            frappe.log_error(
                title="Unicommerce B2B: export job failed", message=str(response)
            )
            return None
        time.sleep(_POLL_INTERVAL_SECONDS)

    frappe.log_error(
        title="Unicommerce B2B: export job timed out",
        message=f"{job_code} did not complete within {_POLL_TIMEOUT_SECONDS}s",
    )
    return None


def _download_rows(file_url: str) -> list[dict]:
    """The export's own column captions, mapped to the few fields we use.

    Only the order code and channel are read here. Everything else about an
    order is taken from `get_sales_order`, which is authoritative and carries
    the tax, address and per-unit price detail the CSV flattens away -- the
    export exists to answer "which orders exist", nothing more.
    """
    content = requests.get(file_url, timeout=_DOWNLOAD_TIMEOUT_SECONDS).content
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    rows = []
    for row in reader:
        rows.append({
            "code": (row.get("Sale Order Code") or "").strip(),
            "channel": (row.get("Channel Name") or "").strip(),
            "status": (row.get("Sale Order Status") or "").strip(),
        })
    return rows


def _facility_header() -> dict:
    """Every export endpoint rejects a call carrying no facility, and says so
    as a 403 reading "Illegal Access, facility is required" -- which looks
    exactly like a missing access resource and is not one.

    Takes the first enabled warehouse mapping, the same source the purchase
    order sync uses, rather than introducing a second place to configure a
    facility code.
    """
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    codes = [row.unicommerce_facility_code for row in settings.warehouse_mapping if row.enabled]
    return {"Facility": codes[0]} if codes else {}


def _as_utc(value) -> str:
    """Same conversion every other Unicommerce call uses, just with the
    milliseconds the export API's date range wants. This used to do its own
    `strftime` with no conversion at all, stamping site-local wall clock
    with a "Z" -- a second, quietly disagreeing answer to the question
    `_to_utc` already answers. One conversion, one place."""
    return _to_utc(value).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@frappe.whitelist()
def run_full_b2b_import(client: UnicommerceClient = None, days: int = 120):
    """Operator entry point: ignore the toggle and sweep a wide window.

    Deliberately not on any schedule. `last_b2b_sync` is left alone so a
    catch-up import never makes the routine sync think it has less to do.
    """
    frappe.only_for("System Manager")
    return sync_b2b_orders(client=client, force=True, lookback_days=int(days))
