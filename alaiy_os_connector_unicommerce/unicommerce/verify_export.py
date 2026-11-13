# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Read-only comparison of a Unicommerce "Search Orders" CSV export with the portal's Sales Orders.

Writes nothing. Orders are matched on the export's `Order #` (the order code the connector stores).
Prints, per day of the channel's order time (the date the portal files an order under), how many
orders each side holds, then the orders the export has that the portal lacks (by channel, status
and day), the portal orders on those days that the export lacks, and shared orders whose status or
price differ. Only order codes are printed, never customer fields.

  bench --site <site> execute alaiy_os_connector_unicommerce.unicommerce.verify_export.run \
    --kwargs "{'path': '/home/ubuntu/orders.csv'}"
"""

import csv
from collections import Counter, defaultdict

import frappe

from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD, ORDER_STATUS_FIELD

SAMPLE = 20


def run(path: str):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        export = {r["Order #"]: r for r in csv.DictReader(fh) if r.get("Order #")}
    days = sorted({r["Channel Created At"][:10] for r in export.values() if r["Channel Created At"]})
    first, last = days[0], days[-1]

    portal = {
        r.code: r for r in frappe.db.sql(
            f"""
            SELECT `{ORDER_CODE_FIELD}` AS code, transaction_date AS day, docstatus, base_grand_total AS total,
                   `{ORDER_STATUS_FIELD}` AS status
            FROM `tabSales Order`
            WHERE transaction_date BETWEEN %(first)s AND %(last)s
              AND `{ORDER_CODE_FIELD}` IS NOT NULL AND `{ORDER_CODE_FIELD}` != ''
            """,
            {"first": first, "last": last}, as_dict=True,
        )
    }

    per_day = defaultdict(lambda: [0, 0])
    for r in export.values():
        per_day[r["Channel Created At"][:10]][0] += 1
    for r in portal.values():
        per_day[str(r.day)][1] += 1
    print(f"export orders: {len(export)}  portal orders {first}..{last}: {len(portal)}\n", flush=True)
    print("day (channel time)   export  portal", flush=True)
    for day in sorted(per_day):
        print(f"{day}        {per_day[day][0]:>8}  {per_day[day][1]:>6}", flush=True)

    # The portal also holds the order under an unconverted/other day sometimes; look the rest up on its own.
    absent = [c for c in export if c not in portal]
    elsewhere = {
        r.code: r for r in frappe.db.sql(
            f"SELECT `{ORDER_CODE_FIELD}` AS code, transaction_date AS day, docstatus, `{ORDER_STATUS_FIELD}` AS status "
            f"FROM `tabSales Order` WHERE `{ORDER_CODE_FIELD}` IN %(codes)s",
            {"codes": tuple(absent) or ("",)}, as_dict=True,
        )
    }
    truly_missing = [c for c in absent if c not in elsewhere]
    print(f"\nin the export, not in the portal on those days: {len(absent)}", flush=True)
    print(f"  of which the portal holds under another day: {len(absent) - len(truly_missing)}", flush=True)
    print(f"  of which not in the portal at all: {len(truly_missing)}", flush=True)
    print("  by channel:", dict(Counter(export[c]["Channel"] for c in truly_missing).most_common()), flush=True)
    print("  by status:", dict(Counter(export[c]["Status"] for c in truly_missing).most_common()), flush=True)
    print("  by day:", dict(sorted(Counter(export[c]["Channel Created At"][:10] for c in truly_missing).items())), flush=True)
    print("  sample:", truly_missing[:SAMPLE], flush=True)

    not_in_export = [c for c in portal if c not in export]
    print(f"\nin the portal, not in the export: {len(not_in_export)}", flush=True)
    print("  by status:", dict(Counter(portal[c].status for c in not_in_export).most_common()), flush=True)
    print("  sample:", not_in_export[:SAMPLE], flush=True)

    status_diff, price_diff = Counter(), []
    for code in set(export) & set(portal):
        a, b = export[code]["Status"], portal[code].status
        if (a or "") != (b or ""):
            status_diff[f"export {a} / portal {b}"] += 1
        try:
            if abs(float(export[code]["Order Price"] or 0) - float(portal[code].total or 0)) > 1:
                price_diff.append(code)
        except ValueError:
            pass
    print(f"\nstatus differs on {sum(status_diff.values())} shared orders:", flush=True)
    for k, n in status_diff.most_common(10):
        print(f"  {k}: {n}", flush=True)
    print(f"order price differs by more than 1 rupee on {len(price_diff)} shared orders; sample: {price_diff[:SAMPLE]}", flush=True)
