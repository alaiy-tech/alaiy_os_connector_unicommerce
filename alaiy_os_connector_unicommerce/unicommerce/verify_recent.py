# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Read-only check of the last few days' orders: Unicommerce against the portal's Sales Orders.

Writes nothing, on either side. For each day it prints how many orders Unicommerce lists
and how many the portal holds, and the order codes Unicommerce has that the portal lacks
(and the reverse). It also compares each shared order's status.

  bench --site <site> execute alaiy_os_connector_unicommerce.unicommerce.verify_recent.run \
    --kwargs "{'days': 5}"
"""

from collections import Counter, defaultdict

import frappe
from frappe.utils import add_days, getdate, nowdate

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.orders import search_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD, ORDER_STATUS_FIELD

SAMPLE = 15


def run(days: int = 5):
    client = UnicommerceClient()
    first = add_days(getdate(nowdate()), -(days - 1))
    # One search per day, so a day with many orders cannot hide behind one page, and the
    # window edges are Unicommerce's own (the site's time zone, as the dashboard's day is).
    uc = {}
    for offset in range(days):
        day = add_days(first, offset)
        elements = search_sales_order(client, from_date=f"{day} 00:00:00", to_date=f"{day} 23:59:59")
        if elements is None:
            print(f"{day}: Unicommerce search FAILED, day not checked", flush=True)
            continue
        for e in elements:
            uc[e.get("code")] = {"day": str(day), "status": e.get("status"), "channel": e.get("channel")}
    # Unicommerce files an order under the day it was created there; the portal files it under the
    # day the channel placed it, which can be much earlier. So an order is looked up by code on any
    # date, not only within these days.
    codes = tuple(uc) or ("",)
    portal_rows = frappe.db.sql(
        f"""
        SELECT `{ORDER_CODE_FIELD}` AS code, transaction_date AS day, docstatus, `{ORDER_STATUS_FIELD}` AS status
        FROM `tabSales Order`
        WHERE `{ORDER_CODE_FIELD}` IN %(codes)s
        """,
        {"codes": codes}, as_dict=True,
    )
    portal = {r.code: r for r in portal_rows}

    per_day = defaultdict(lambda: [0, 0, 0])
    for code, v in uc.items():
        per_day[v["day"]][0] += 1
        if code in portal:
            per_day[v["day"]][1] += 1
        if code in portal and str(portal[code].day) != v["day"]:
            per_day[v["day"]][2] += 1
    print("day (Unicommerce)   unicommerce  in portal  of which filed under another day", flush=True)
    for day in sorted(per_day):
        print(f"{day}        {per_day[day][0]:>10}  {per_day[day][1]:>9}  {per_day[day][2]:>6}", flush=True)

    missing = sorted(set(uc) - set(portal))
    print(f"\nin Unicommerce, not in the portal on any date: {len(missing)}", flush=True)
    print("  by status:", dict(Counter(uc[c]["status"] for c in missing).most_common()), flush=True)
    print("  by channel:", dict(Counter(uc[c]["channel"] for c in missing).most_common()), flush=True)
    print("  by day:", dict(sorted(Counter(uc[c]["day"] for c in missing).items())), flush=True)
    print("  sample:", missing[:SAMPLE], flush=True)

    differ = Counter()
    for code in set(uc) & set(portal):
        a, b = uc[code]["status"], portal[code].status
        if (a or "") != (b or ""):
            differ[f"Unicommerce {a} / portal {b}"] += 1
    print(f"\nstatus differs on {sum(differ.values())} shared orders:", flush=True)
    for k, n in differ.most_common(10):
        print(f"  {k}: {n}", flush=True)


def inspect(code: str):
    """Read-only: fetch one order from Unicommerce and say whether the pull could import it.

      bench --site <site> execute alaiy_os_connector_unicommerce.unicommerce.verify_recent.inspect \
        --kwargs "{'code': '<order code>'}"

    Prints the order's status, channel and placed time, whether the channel is enabled locally, and
    each line's SKU with whether a matching Item exists. No customer fields are printed."""
    from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
    from alaiy_os_connector_unicommerce.unicommerce.constants import ITEM_EXTERNAL_ID_FIELD

    order = get_sales_order(UnicommerceClient(), code)
    if not order:
        print("get_sales_order returned nothing for this code: the pull skips it without logging.", flush=True)
        return
    channel = order.get("channel")
    print("status:", order.get("status"), "| channel:", channel,
          "| placed:", order.get("displayOrderDateTime"), "| existing locally:",
          bool(frappe.db.exists("Sales Order", {ORDER_CODE_FIELD: code})), flush=True)
    print("channel enabled locally:", frappe.db.get_value("Unicommerce Channel", channel, "enabled"), flush=True)
    for line in order.get("saleOrderItems") or []:
        sku = line.get("itemSku")
        print(" line:", sku, "| item in portal:",
              bool(frappe.db.get_value("Item", {ITEM_EXTERNAL_ID_FIELD: sku}, "name")),
              "| line status:", line.get("statusCode"), flush=True)
