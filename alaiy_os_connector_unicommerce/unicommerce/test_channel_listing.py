# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Self-check for the channel-listing mapping's parsing and cardinality.

Runs standalone (no frappe, no site):

    python unicommerce/test_channel_listing.py

The line shapes below are the documented /oms/saleorder/get response
(docs.unicommerce.com/docs/saleorder-get.html): a saleOrderItems entry
carries channelProductId and sellerSkuCode alongside itemSku, and the
channel code sits on the order header as `channel`.

What is worth asserting here is the cardinality and the key. A marketplace
mints an id per listing, so several ids legitimately resolve to one Item,
and the reverse must never happen -- one id resolving to two Items would
mean a Flipkart PO could be read as two different products.
"""


CHANNEL_PRODUCT_ID = "channelProductId"
SELLER_SKU_CODE = "sellerSkuCode"
ITEM_SKU = "itemSku"


def _listing_name(channel, channel_product_id):
    """Verbatim from channel_listing._listing_name."""
    return f"{channel}-{channel_product_id}"


def _pairs_from_order(order):
    """The body of fill_from_order's loop, minus the database.

    Returns [(name, channel, channel_product_id, sku, seller_sku)] for every
    line that carries a listing id.
    """
    channel = (order.get("channel") or "").strip()
    if not channel:
        return []

    out = []
    for line in order.get("saleOrderItems") or []:
        cpid = (line.get(CHANNEL_PRODUCT_ID) or "").strip()
        if not cpid:
            continue
        out.append((
            _listing_name(channel, cpid),
            channel,
            cpid,
            (line.get(ITEM_SKU) or "").strip(),
            (line.get(SELLER_SKU_CODE) or "").strip(),
        ))
    return out


def _line(cpid, sku, seller=None, status="CONFIRMED"):
    return {
        CHANNEL_PRODUCT_ID: cpid,
        ITEM_SKU: sku,
        SELLER_SKU_CODE: seller if seller is not None else sku,
        "statusCode": status,
    }


def test_reads_the_pair_off_a_line():
    order = {
        "channel": "FLIPKART_GLOBALI",
        "code": "SO-1",
        "saleOrderItems": [_line("AASGEYH426PVCVRN", "PJAQPPSTONE_3PC")],
    }
    pairs = _pairs_from_order(order)
    assert len(pairs) == 1, pairs
    name, channel, cpid, sku, seller = pairs[0]
    assert name == "FLIPKART_GLOBALI-AASGEYH426PVCVRN", name
    assert cpid == "AASGEYH426PVCVRN"
    assert sku == "PJAQPPSTONE_3PC"
    assert seller == "PJAQPPSTONE_3PC"


def test_many_listings_map_to_one_item():
    """Flipkart mints an FSN per listing, so one product carries several
    across variants and relistings. All must resolve to the same SKU."""
    order = {
        "channel": "FLIPKART_GLOBALI",
        "code": "SO-2",
        "saleOrderItems": [
            _line("AASGEYH426PVCVRN", "PJAQPPSTONE_3PC"),
            _line("AASGEYH426PVCVRZ", "PJAQPPSTONE_3PC"),
            _line("BBTHFZK937QWDXSM", "PJAQPPSTONE_3PC"),
        ],
    }
    pairs = _pairs_from_order(order)
    assert len(pairs) == 3
    assert len({p[0] for p in pairs}) == 3, "each listing gets its own row"
    assert {p[3] for p in pairs} == {"PJAQPPSTONE_3PC"}, "all resolve to one SKU"


def test_one_listing_never_maps_to_two_items():
    """The key is (channel, listing id), so a second sighting overwrites
    rather than adding. If this ever produced two rows, a Flipkart PO could
    be read as two different products."""
    seen = {}
    for order in (
        {"channel": "FLIPKART_GLOBALI", "code": "SO-3",
         "saleOrderItems": [_line("AASGEYH426PVCVRN", "PJAQPPSTONE_3PC")]},
        {"channel": "FLIPKART_GLOBALI", "code": "SO-4",
         "saleOrderItems": [_line("AASGEYH426PVCVRN", "PJAQPPSTONE_3PC")]},
    ):
        for name, _c, _cpid, sku, _s in _pairs_from_order(order):
            seen[name] = sku
    assert len(seen) == 1, seen
    assert seen["FLIPKART_GLOBALI-AASGEYH426PVCVRN"] == "PJAQPPSTONE_3PC"


def test_same_listing_id_on_two_channels_stays_separate():
    """The id is only unique within a marketplace, so the channel is part of
    the key -- otherwise one marketplace's listing would silently overwrite
    another's."""
    a = _pairs_from_order({"channel": "FLIPKART_GLOBALI", "code": "SO-5",
                           "saleOrderItems": [_line("SHARED_ID", "SKU_A")]})
    b = _pairs_from_order({"channel": "AMAZON_GLOBALI", "code": "SO-6",
                           "saleOrderItems": [_line("SHARED_ID", "SKU_B")]})
    assert a[0][0] != b[0][0], (a[0][0], b[0][0])


def test_line_without_a_listing_id_is_skipped():
    """Not every channel supplies one. A line without it is not a listing
    this can map, and must not produce a row keyed on an empty id."""
    order = {
        "channel": "CUSTOM",
        "code": "SO-7",
        "saleOrderItems": [
            _line("", "SKU_A"),
            {ITEM_SKU: "SKU_B"},              # field absent entirely
            _line(None, "SKU_C"),
            _line("REAL_ID", "SKU_D"),
        ],
    }
    pairs = _pairs_from_order(order)
    assert len(pairs) == 1, pairs
    assert pairs[0][2] == "REAL_ID"


def test_order_without_a_channel_records_nothing():
    """A row keyed on an empty channel would collide with every other."""
    assert _pairs_from_order({"code": "SO-8", "saleOrderItems": [_line("X", "Y")]}) == []
    assert _pairs_from_order({"channel": "  ", "code": "SO-9",
                              "saleOrderItems": [_line("X", "Y")]}) == []


def test_seller_sku_can_differ_from_the_item_sku():
    """Both are kept because they are not always the same value -- the
    seller's own code for a listing can drift from the SKU it fulfils."""
    order = {"channel": "FLIPKART_GLOBALI", "code": "SO-10",
             "saleOrderItems": [_line("FSN1", "MASTER_SKU", seller="SELLER_CODE_9")]}
    _n, _c, _cpid, sku, seller = _pairs_from_order(order)[0]
    assert sku == "MASTER_SKU"
    assert seller == "SELLER_CODE_9"


def test_whitespace_is_stripped_from_the_key():
    """A padded id would key a second row for the same listing."""
    order = {"channel": "FLIPKART_GLOBALI", "code": "SO-11",
             "saleOrderItems": [_line("  FSN_PADDED  ", "  SKU  ")]}
    name, _c, cpid, sku, _s = _pairs_from_order(order)[0]
    assert cpid == "FSN_PADDED", repr(cpid)
    assert sku == "SKU", repr(sku)
    assert name == "FLIPKART_GLOBALI-FSN_PADDED"


# --- the daily catch-up's own logic, without frappe -------------------------
#
# What matters is that it resumes, terminates, and never refetches an order
# twice: a pass that restarted from the top would refetch the same 200
# orders every day and never reach the rest, which is exactly the
# misconfiguration this is meant to be immune to.

_CATCHUP_BATCH = 200


def _catch_up_pass(orders, batch=_CATCHUP_BATCH):
    """One pass: take the oldest unchecked orders, mark them, return counts.

    `orders` is [{"code", "checked", "lines"}], oldest first -- mirroring
    the query's order_by="creation asc" and its unchecked filter.
    """
    todo = [o for o in orders if not o["checked"]][:batch]
    recorded = 0
    for order in todo:
        recorded += len([l for l in order["lines"] if l.get(CHANNEL_PRODUCT_ID)])
        order["checked"] = True          # marked either way
    remaining = len([o for o in orders if not o["checked"]])
    return {"orders": len(todo), "listings_recorded": recorded, "remaining": remaining}


def _orders(n, with_listing=True):
    return [
        {"code": f"SO-{i}", "checked": False,
         "lines": [_line(f"FSN{i}", f"SKU{i}")] if with_listing else [{ITEM_SKU: f"SKU{i}"}]}
        for i in range(n)
    ]


def test_catch_up_resumes_rather_than_restarting():
    orders = _orders(500)
    first = _catch_up_pass(orders)
    assert first["orders"] == 200 and first["remaining"] == 300, first
    second = _catch_up_pass(orders)
    assert second["orders"] == 200 and second["remaining"] == 100, second
    third = _catch_up_pass(orders)
    assert third["orders"] == 100 and third["remaining"] == 0, third


def test_catch_up_goes_quiet_once_history_is_done():
    """Left scheduled forever, so it has to cost nothing when finished."""
    orders = _orders(10)
    _catch_up_pass(orders)
    idle = _catch_up_pass(orders)
    assert idle == {"orders": 0, "listings_recorded": 0, "remaining": 0}, idle


def test_orders_without_listing_ids_are_still_marked():
    """A channel that supplies no channelProductId has nothing to record --
    but leaving those unmarked would refetch them daily forever."""
    orders = _orders(5, with_listing=False)
    first = _catch_up_pass(orders)
    assert first["listings_recorded"] == 0, first
    assert first["remaining"] == 0, "unmapped orders must not be retried forever"
    assert _catch_up_pass(orders)["orders"] == 0


def test_catch_up_never_reads_one_order_twice():
    orders = _orders(300)
    seen = []
    for _ in range(3):
        seen += [o["code"] for o in orders if not o["checked"]][:_CATCHUP_BATCH]
        _catch_up_pass(orders)
    assert len(seen) == len(set(seen)) == 300, (len(seen), len(set(seen)))


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  PASS  {name}")
    print(f"\n{passed} passed")
