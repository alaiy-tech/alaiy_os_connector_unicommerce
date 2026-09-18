# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Reconcile local Sales Orders against Unicommerce's real order data.

Read-only. Makes no writes to either side -- only GET/search calls to
Unicommerce and frappe.db.sql reads locally. Confirmed live: this site's
"synced" signal (a non-empty unicommerce_order_code on Sales Order) only
ever proves a one-time successful pull; nothing re-verifies status parity
afterward beyond a short rolling window (order_status_days, default 2,
capped 14) -- an order that drifted or failed silently outside that
window looks "synced" locally forever with no code path that would
ever notice Unicommerce disagrees. This script is the missing check.

Walks Unicommerce's real saleOrder/search in 31-day windows (its own
search cap) from the earliest local order's date to today, paging each
window with the same displayStart/displayLength pattern
order/sync_old_orders.py already uses, and diffs the resulting
{order_code: status} map against what is stored locally.

    bench --site globali.os.alaiy.com execute \
      alaiy_os_connector_unicommerce.scripts.reconcile_orders.run

Options, passed as kwargs:

    --kwargs "{'from_date': '2026-01-01'}"   start earlier/later than the
                                              earliest local order
    --kwargs "{'to_date': '2026-09-01'}"     stop before today
    --kwargs "{'every': 5}"                  print a progress line every
                                              N windows (default 1)

Prints a summary at the end: counts, and up to 50 example rows per
mismatch category (more are still counted, just not all printed --
this is a diagnostic pass, not a fix).
"""

import time

import frappe
from frappe.utils import add_days, getdate, today

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.orders import _utc_timeformat
from alaiy_os_connector_unicommerce.unicommerce.constants import (
	ORDER_CODE_FIELD, ORDER_STATUS_FIELD,
)
from alaiy_os_connector_unicommerce.unicommerce.order.sync_old_orders import _request_with_retry

SEARCH_ENDPOINT = "/services/rest/v1/oms/saleOrder/search"
PAGE_SIZE = 1000
WINDOW_DAYS = 31  # Unicommerce's own search cap, same as sync_old_orders.py


def _local_orders():
	"""{order_code: (sales_order_name, local_status)} for every Sales Order
	that has ever been pulled from Unicommerce (non-empty order code) --
	orders with no code were never linked to Unicommerce at all and are out
	of scope for this comparison."""
	rows = frappe.db.sql(
		f"""
		SELECT name, `{ORDER_CODE_FIELD}` AS code, `{ORDER_STATUS_FIELD}` AS status
		FROM `tabSales Order`
		WHERE IFNULL(`{ORDER_CODE_FIELD}`, '') != ''
		""",
		as_dict=True,
	)
	return {r.code: (r.name, r.status) for r in rows}


def _earliest_local_date():
	row = frappe.db.sql(
		f"""
		SELECT MIN(transaction_date) AS d FROM `tabSales Order`
		WHERE IFNULL(`{ORDER_CODE_FIELD}`, '') != ''
		""",
		as_dict=True,
	)
	return row[0].d if row and row[0].d else getdate(add_days(today(), -365))


def _date_windows(from_date, to_date):
	start = getdate(from_date)
	end = getdate(to_date)
	while start <= end:
		window_end = min(add_days(start, WINDOW_DAYS - 1), end)
		yield start, window_end
		start = add_days(window_end, 1)


def _fetch_window(client, window_start, window_end):
	"""Every {code: status} pair Unicommerce reports in this window,
	paged. Mirrors sync_old_orders.py's own pagination shape."""
	base_body = {
		"fromDate": _utc_timeformat(f"{window_start} 00:00:00"),
		"toDate": _utc_timeformat(f"{window_end} 23:59:59"),
		"dateType": "CREATED",
	}
	display_start = 0
	out = {}
	while True:
		body = dict(base_body)
		body["searchOptions"] = {
			"displayStart": display_start, "displayLength": PAGE_SIZE, "getCount": display_start == 0,
		}
		resp, ok = _request_with_retry(client, body)
		if not ok or resp is None:
			frappe.log_error(
				title="Unicommerce: reconcile_orders search failed",
				message=f"Search failed at displayStart={display_start} for window {window_start} -> {window_end}.",
			)
			return out, False
		elements = resp.get("elements") or []
		if not elements:
			return out, True
		for element in elements:
			code = element.get("code")
			if code:
				out[code] = element.get("status")
		if len(elements) < PAGE_SIZE:
			return out, True
		display_start += PAGE_SIZE


def run(from_date=None, to_date=None, every=1):
	client = UnicommerceClient()
	local = _local_orders()
	print(f"Local: {len(local)} Sales Orders with a Unicommerce order code.")

	from_date = getdate(from_date) if from_date else _earliest_local_date()
	to_date = getdate(to_date) if to_date else getdate(today())
	print(f"Reconciling Unicommerce orders CREATED {from_date} .. {to_date} (31-day windows)")

	remote = {}
	incomplete_windows = []
	windows = list(_date_windows(from_date, to_date))
	start_time = time.time()
	for i, (w_start, w_end) in enumerate(windows, 1):
		window_map, ok = _fetch_window(client, w_start, w_end)
		remote.update(window_map)
		if not ok:
			incomplete_windows.append((w_start, w_end))
		if i % every == 0 or i == len(windows):
			elapsed = time.time() - start_time
			print(f"  [{i}/{len(windows)}] {w_start} -> {w_end}: {len(window_map)} orders "
			      f"(running total {len(remote)}, {elapsed:.0f}s elapsed)")

	print(f"\nUnicommerce: {len(remote)} orders found across {len(windows)} windows.")
	if incomplete_windows:
		print(f"WARNING: {len(incomplete_windows)} window(s) failed to fetch cleanly -- "
		      f"results below are a lower bound, not exhaustive. Re-run with from_date/to_date "
		      f"narrowed to just the failed window(s) to retry: {incomplete_windows[:5]}")

	local_codes = set(local)
	remote_codes = set(remote)

	missing_locally = sorted(remote_codes - local_codes)
	missing_on_unicommerce = sorted(local_codes - remote_codes)
	status_mismatch = sorted(
		code for code in (local_codes & remote_codes)
		if (local[code][1] or "") != (remote[code] or "")
	)

	print("\n" + "=" * 70)
	print(f"On Unicommerce, NO local Sales Order: {len(missing_locally)}")
	for code in missing_locally[:50]:
		print(f"  {code}  (Unicommerce status: {remote[code]})")

	print(f"\nLocal Sales Order, NOT found on Unicommerce in this range: {len(missing_on_unicommerce)}")
	print("  (a real gap only if within the reconciled date range -- an order")
	print("   created outside from_date/to_date will show up here as a false")
	print("   positive; re-run with a wider range to confirm)")
	for code in missing_on_unicommerce[:50]:
		so_name, local_status = local[code]
		print(f"  {code} ({so_name})  local status: {local_status}")

	print(f"\nStatus mismatch (exists both sides, status differs): {len(status_mismatch)}")
	for code in status_mismatch[:50]:
		so_name, local_status = local[code]
		print(f"  {code} ({so_name})  local: {local_status}  unicommerce: {remote[code]}")

	print("=" * 70)
	print(f"\nSummary: {len(local)} local / {len(remote)} remote / "
	      f"{len(missing_locally)} missing-locally / {len(missing_on_unicommerce)} missing-on-unicommerce / "
	      f"{len(status_mismatch)} status-mismatch")

	return {
		"local_count": len(local),
		"remote_count": len(remote),
		"missing_locally": missing_locally,
		"missing_on_unicommerce": missing_on_unicommerce,
		"status_mismatch": status_mismatch,
		"incomplete_windows": incomplete_windows,
	}
