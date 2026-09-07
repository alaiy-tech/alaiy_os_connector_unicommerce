"""Marks whether an order's marketplace listings have been read.

Every order pulled from now on records its listings as it arrives. Orders
already in the database when that landed never had their channelProductId
read, and the only way to recover it is to refetch each one -- an API call
per order, so it has to be paced rather than run in one go.

This field is what lets the daily catch-up resume instead of restarting,
and what lets it eventually go quiet: an order is marked whether or not it
yielded a listing, so a channel that supplies no channelProductId is not
refetched every day forever.

Existing orders start unchecked, which is exactly right -- that is the work
the catch-up exists to do.

Idempotent -- safe to re-run.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Sales Order": [
            {
                "fieldname": "unicommerce_listings_checked",
                "label": "Unicommerce Listings Read",
                "fieldtype": "Check",
                "default": "0",
                "insert_after": "unicommerce_channel_id",
                "read_only": 1,
                "hidden": 1,
                "no_copy": 1,
                "search_index": 1,
                "description": (
                    "Whether this order has been read for the marketplace listing ids "
                    "on its lines. Bookkeeping for the daily catch-up, not a business "
                    "field."
                ),
            },
        ]
    })
