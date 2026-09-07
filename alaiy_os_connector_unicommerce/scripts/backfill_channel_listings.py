# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Read marketplace listing ids off orders already pulled, with live progress.

A one-off. Ongoing capture happens in the order pull itself, and history is
cleared by the daily catch-up -- this exists only to do the same work now
rather than over weeks, when someone wants the mapping today.

    bench --site globali.os.alaiy.com execute \
      alaiy_os_connector_unicommerce.scripts.backfill_channel_listings.run

Options, passed as kwargs:

    --kwargs "{'limit': 500}"       stop after 500 orders
    --kwargs "{'every': 10}"        print a line every 10 orders (default 25)
    --kwargs "{'channel': 'FLIPKART_GLOBALI'}"    one channel only

Why it lives in scripts/ and not beside the sync modules: it is an
operator tool, not part of any sync path. Nothing imports it, nothing schedules it, and it can
be interrupted at any point -- each order is committed as it is read, so a
Ctrl-C keeps everything already done and the daily job picks up the rest.

It prints as it goes because the thing that made this painful was not
knowing whether a silent process was working, stuck, or dead.
"""

import time

import frappe

from alaiy_os_connector_unicommerce.unicommerce.channel_listing import (
	LISTINGS_CHECKED_FIELD,
	_mark_checked,
	fill_from_order,
)
from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD


def _fmt_eta(seconds):
	if seconds < 60:
		return f"{int(seconds)}s"
	if seconds < 3600:
		return f"{int(seconds // 60)}m"
	return f"{seconds / 3600:.1f}h"


def run(limit=None, every=25, channel=None):
	"""Walk unread orders oldest-first, recording their listings.

	Prints a progress line every `every` orders: how many done, how many
	listings found, the rate, and an estimate of what is left. Any order
	that fails is named and skipped rather than stopping the run -- one bad
	order out of ten thousand should not end the job.
	"""
	limit = int(limit) if limit else None
	every = int(every) if every else 25

	if not frappe.db.has_column("Sales Order", LISTINGS_CHECKED_FIELD):
		print("The listings-checked field is missing -- run `bench migrate` first.")
		return

	filters = {ORDER_CODE_FIELD: ["is", "set"], LISTINGS_CHECKED_FIELD: 0}
	if channel:
		filters["unicommerce_channel_id"] = channel

	total_unread = frappe.db.count("Sales Order", filters)
	codes = frappe.get_all(
		"Sales Order", filters=filters, pluck=ORDER_CODE_FIELD,
		limit=limit or 0, order_by="creation asc",
	)
	codes = [c for c in dict.fromkeys(codes) if c]

	listings_before = frappe.db.count("Unicommerce Channel Listing")

	print(f"\n  {total_unread:,} orders unread" + (f" on {channel}" if channel else ""))
	print(f"  {len(codes):,} to read in this run")
	print(f"  {listings_before:,} listings already recorded")
	print("  Ctrl-C is safe -- each order is committed as it is read.\n")

	client = UnicommerceClient()
	started = time.time()
	done = recorded = failed = 0

	try:
		for code in codes:
			try:
				order = get_sales_order(client, code)
				if order:
					recorded += fill_from_order(order)
				# Marked either way: an order whose channel supplies no
				# listing id has nothing to record and must not be read
				# again tomorrow.
				_mark_checked(code)
				frappe.db.commit()
			except Exception as exc:
				failed += 1
				# Named, not swallowed. A run that quietly skipped a
				# thousand orders would look identical to a clean one.
				print(f"    ! {code}: {str(exc)[:120]}")
				frappe.log_error(
					title=f"Unicommerce listing backfill failed for {code}",
					message=frappe.get_traceback(),
				)

			done += 1
			if done % every == 0 or done == len(codes):
				elapsed = time.time() - started
				rate = done / elapsed if elapsed else 0
				left = (len(codes) - done) / rate if rate else 0
				print(
					f"  {done:>6,}/{len(codes):,}"
					f"  {recorded:>5,} listings"
					f"  {rate:4.1f}/s"
					f"  ~{_fmt_eta(left)} left"
					+ (f"  {failed} failed" if failed else "")
				)
	except KeyboardInterrupt:
		print("\n  Stopped. Everything read so far is saved.")

	elapsed = time.time() - started
	listings_after = frappe.db.count("Unicommerce Channel Listing")
	remaining = frappe.db.count(
		"Sales Order", {ORDER_CODE_FIELD: ["is", "set"], LISTINGS_CHECKED_FIELD: 0}
	)

	print(f"\n  read {done:,} orders in {_fmt_eta(elapsed)}")
	print(f"  {listings_after - listings_before:,} new listings ({listings_after:,} total)")
	if failed:
		print(f"  {failed:,} orders failed -- see the Error Log")
	print(f"  {remaining:,} orders still unread"
	      + ("" if not remaining else " -- the daily job will clear these"))

	by_channel = frappe.db.sql(
		"""SELECT channel, COUNT(*) listings, COUNT(DISTINCT item_code) items
		   FROM `tabUnicommerce Channel Listing` GROUP BY 1 ORDER BY 2 DESC""",
		as_dict=True,
	)
	if by_channel:
		print("\n  channel                          listings   items")
		for row in by_channel:
			print(f"  {row.channel:<32} {row.listings:>8,} {row.items:>7,}")
	print()

	return {
		"orders_read": done, "listings_new": listings_after - listings_before,
		"failed": failed, "remaining": remaining,
	}
