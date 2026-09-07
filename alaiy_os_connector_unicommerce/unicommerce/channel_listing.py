# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Which marketplace listing a Unicommerce SKU is sold under.

Flipkart's purchase orders name only the FSN. Every decision made against
one -- what to buy, what is in stock, what the fill rate was -- is made per
master SKU, and neither side derives the other. Globali mapped ~1,600 items
by hand inside Unicommerce for exactly this reason, and the portal cannot
read that table, so it has been maintained a second time by hand. A listing
missed in the second copy is invisible to procurement, and the shortfall is
under-ordered by precisely that quantity, silently.

Where this comes from
---------------------
Every sale order line already carries both halves:

    channelProductId   the marketplace's own id -- Flipkart's FSN
    itemSku            Unicommerce's SKU, which resolves to an Item here

The connector read itemSku and dropped the rest. This records the pair, so
the mapping accumulates from orders the connector was already pulling. No
new API call, no new schedule, nothing to backfill separately -- an order
sync that runs today produces the mapping for every listing it touches.

What it cannot do
-----------------
Only listings that have sold appear. A brand-new listing with no orders yet
is absent, which matters because that is exactly the case procurement needs
before the first PO arrives. Unicommerce has a write endpoint for channel
item types (/services/rest/v1/channel/createChannelItemType) but publishes
no read or search counterpart, so there is no supported way to pull the
full table -- see the module's own note in fill_from_order for what would
change if one appears.

Cardinality is many-to-one on purpose: a marketplace mints an id per
listing, so one product carries several across variants and relistings.
"""

import frappe
from frappe.utils import now_datetime

LISTING_DOCTYPE = "Unicommerce Channel Listing"

# Unicommerce's own field names on a sale order line.
CHANNEL_PRODUCT_ID = "channelProductId"
SELLER_SKU_CODE = "sellerSkuCode"
ITEM_SKU = "itemSku"

# Set on a Sales Order once its listings have been read, so the daily
# catch-up resumes rather than restarting and eventually goes quiet.
LISTINGS_CHECKED_FIELD = "unicommerce_listings_checked"


def _listing_name(channel: str, channel_product_id: str) -> str:
	"""Mirrors the doctype's autoname so a row can be found without a query
	that has to know the naming scheme."""
	return f"{channel}-{channel_product_id}"


def record_listing(channel: str, line: dict, item_code: str | None = None) -> str | None:
	"""Record one (channel, channel product id) -> Item mapping.

	Idempotent: re-running an order sync updates last_seen_on and the count
	rather than creating a second row, so this is safe on the incremental
	pull and on a full historical re-import alike.

	Returns the row name, or None when the line carries no channel product
	id -- which is normal. Not every channel supplies one, and a line
	without one is simply not a listing this can map.
	"""
	channel_product_id = (line.get(CHANNEL_PRODUCT_ID) or "").strip()
	if not channel or not channel_product_id:
		return None

	sku = (line.get(ITEM_SKU) or "").strip()
	seller_sku = (line.get(SELLER_SKU_CODE) or "").strip()
	name = _listing_name(channel, channel_product_id)
	now = now_datetime()

	if frappe.db.exists(LISTING_DOCTYPE, name):
		updates = {"last_seen_on": now}
		# The Item can arrive later than the first order: a line whose SKU
		# had no Item yet still recorded the mapping, and this fills it in
		# once the product import catches up.
		if item_code and not frappe.db.get_value(LISTING_DOCTYPE, name, "item_code"):
			updates["item_code"] = item_code
		frappe.db.set_value(LISTING_DOCTYPE, name, updates, update_modified=False)
		frappe.db.sql(
			f"UPDATE `tab{LISTING_DOCTYPE}` SET seen_count = seen_count + 1 WHERE name = %s",
			name,
		)
		return name

	doc = frappe.new_doc(LISTING_DOCTYPE)
	doc.channel = channel
	doc.channel_product_id = channel_product_id
	doc.item_code = item_code
	doc.seller_sku_code = seller_sku
	doc.unicommerce_sku = sku
	doc.first_seen_on = now
	doc.last_seen_on = now
	doc.seen_count = 1
	doc.insert(ignore_permissions=True)
	return doc.name


def fill_from_order(order: dict) -> int:
	"""Record every listing on one Unicommerce sale order.

	Called from the order pull, after the order itself is handled. Never
	raises: a mapping that cannot be written must not fail the order that
	carried it -- the order is the thing with money attached, and the
	mapping will be recorded again by the next order on that listing.

	If Unicommerce ever publishes a read endpoint for channel item types,
	that becomes the better source (it would include listings that have
	never sold) and this becomes the fallback that keeps it current.
	"""
	from alaiy_os_connector_unicommerce.unicommerce.constants import ITEM_EXTERNAL_ID_FIELD

	channel = (order.get("channel") or "").strip()
	if not channel:
		return 0

	recorded = 0
	for line in order.get("saleOrderItems") or []:
		try:
			sku = (line.get(ITEM_SKU) or "").strip()
			item_code = (
				frappe.db.get_value("Item", {ITEM_EXTERNAL_ID_FIELD: sku}, "name")
				if sku else None
			)
			if record_listing(channel, line, item_code):
				recorded += 1
		except Exception:
			frappe.log_error(
				title=f"Unicommerce: could not record listing on {order.get('code')}",
				message=frappe.get_traceback(),
			)
	return recorded


def item_for_channel_product(channel_product_id: str, channel: str | None = None) -> str | None:
	"""The Item a marketplace listing id resolves to.

	What the Minutes PO flow calls with an FSN off a Flipkart PO. Channel is
	optional: ids are marketplace-unique in practice, and a PO does not
	always name the channel in the same vocabulary the order did.
	"""
	if not channel_product_id:
		return None
	filters = {"channel_product_id": channel_product_id.strip()}
	if channel:
		filters["channel"] = channel
	return frappe.db.get_value(LISTING_DOCTYPE, filters, "item_code")


@frappe.whitelist()
def get_mapping(channel_product_id: str, channel: str | None = None) -> dict:
	"""Resolve one listing id, for the portal.

	Returns the Item and how confident that answer is: a mapping last seen
	months ago is still worth returning, but the caller deserves to know.
	"""
	frappe.has_permission(LISTING_DOCTYPE, "read", throw=True)

	filters = {"channel_product_id": (channel_product_id or "").strip()}
	if channel:
		filters["channel"] = channel
	row = frappe.db.get_value(
		LISTING_DOCTYPE, filters,
		["name", "channel", "item_code", "unicommerce_sku", "last_seen_on", "seen_count"],
		as_dict=True,
	)
	return row or {}


# How many historical orders one scheduled catch-up pass will refetch. Each
# is its own API call, so this is a rate-limit budget, not a performance
# knob: 200/day clears a few thousand unmapped orders within a fortnight
# without ever competing with the order sync for quota.
_CATCHUP_BATCH = 200


def catch_up_on_unmapped_orders() -> dict:
	"""Daily pass over orders that predate this mapping.

	Every order pulled from now on records its listings as it arrives, so
	this exists only for history -- orders already in the database when the
	feature landed, which never had their channelProductId read.

	Self-limiting rather than one long job: it takes a fixed batch of the
	oldest unseen orders each day and stops. Once history is exhausted it
	finds nothing and costs one query, so it can be left scheduled forever
	rather than being a one-off someone has to remember to run and a
	deployment that quietly misses it.

	Tracks progress on the Sales Order itself, so an interrupted run resumes
	where it stopped instead of starting over.
	"""
	from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
	from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
	from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD

	if not frappe.db.has_column("Sales Order", LISTINGS_CHECKED_FIELD):
		# The field arrives with the patch; until then there is nothing to
		# track progress on and a pass would refetch the same orders daily.
		return {"skipped": "listings-checked field not present yet"}

	codes = frappe.get_all(
		"Sales Order",
		filters={
			ORDER_CODE_FIELD: ["is", "set"],
			LISTINGS_CHECKED_FIELD: 0,
		},
		pluck=ORDER_CODE_FIELD,
		limit=_CATCHUP_BATCH,
		order_by="creation asc",
	)
	codes = [c for c in dict.fromkeys(codes) if c]
	if not codes:
		return {"orders": 0, "listings_recorded": 0, "remaining": 0}

	client = UnicommerceClient()
	recorded = failed = 0
	for code in codes:
		try:
			order = get_sales_order(client, code)
			if order:
				recorded += fill_from_order(order)
			# Marked either way. An order whose channel supplies no
			# channelProductId has nothing to record and must not be
			# refetched every day forever.
			_mark_checked(code)
		except Exception:
			failed += 1
			frappe.log_error(
				title=f"Unicommerce listing catch-up failed for {code}",
				message=frappe.get_traceback(),
			)
	frappe.db.commit()

	remaining = frappe.db.count("Sales Order", {
		ORDER_CODE_FIELD: ["is", "set"], LISTINGS_CHECKED_FIELD: 0,
	})
	return {
		"orders": len(codes), "listings_recorded": recorded,
		"failed": failed, "remaining": remaining,
	}


def _mark_checked(order_code: str) -> None:
	"""Record that this order's listings have been read.

	db.sql rather than set_value: these are submitted documents and this is
	bookkeeping, not a change anyone should see in the document's own
	modified timestamp or version history.
	"""
	from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD

	frappe.db.sql(
		f"UPDATE `tabSales Order` SET `{LISTINGS_CHECKED_FIELD}` = 1 "
		f"WHERE `{ORDER_CODE_FIELD}` = %s",
		order_code,
	)


def backfill_from_existing_orders(limit: int = None) -> dict:
	"""Recover mappings from orders already pulled, by re-reading them from
	Unicommerce.

	The pair is only on the API payload -- the local Sales Order keeps the
	SKU and not the listing id -- so this refetches each order rather than
	reading the database. That makes it slow and rate-limited, which is why
	it is a one-off rather than a schedule: from here on the order pull
	records mappings as they arrive.

	Worth running once after deploy so the listings already sold are known
	without waiting for each to sell again.

	    bench --site <site> execute \
	      alaiy_os_connector_unicommerce.unicommerce.channel_listing.backfill_from_existing_orders
	"""
	from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
	from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
	from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD

	codes = frappe.get_all(
		"Sales Order",
		filters={ORDER_CODE_FIELD: ["is", "set"]},
		pluck=ORDER_CODE_FIELD,
		limit=limit or 0,
		order_by="creation desc",
	)
	codes = [c for c in dict.fromkeys(codes) if c]

	client = UnicommerceClient()
	recorded = failed = 0
	for code in codes:
		try:
			order = get_sales_order(client, code)
			if order:
				recorded += fill_from_order(order)
			if frappe.db.has_column("Sales Order", LISTINGS_CHECKED_FIELD):
				_mark_checked(code)
		except Exception:
			failed += 1
			frappe.log_error(
				title=f"Unicommerce listing backfill failed for {code}",
				message=frappe.get_traceback(),
			)
	frappe.db.commit()
	return {"orders": len(codes), "listings_recorded": recorded, "failed": failed}
