# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
One-off: populate unicommerce_is_cod on Sales Orders pulled before the field
existed.

order/pull.py always wrote the COD flag, but setup_custom_fields only ever
created the field on Customer and Sales Invoice -- Frappe drops an unknown
fieldname silently on insert, so every order pulled before that fix has a
blank flag with no error anywhere to show for it.

Re-reads the real value from Unicommerce (saleorder/get carries `cod` at the
top level) rather than inferring it, and writes with db.set_value so a
submitted Sales Order is updated without a cancel/amend cycle -- this is a
reporting flag, not a financial field.

Usage:
    bench --site <site> execute \
        alaiy_os_connector_unicommerce.patches.backfill_sales_order_cod.run

    # preview without writing:
    bench --site <site> execute \
        alaiy_os_connector_unicommerce.patches.backfill_sales_order_cod.run \
        --kwargs "{'dry_run': True}"

    # narrow the window (default: every order with a blank flag):
    bench --site <site> execute \
        alaiy_os_connector_unicommerce.patches.backfill_sales_order_cod.run \
        --kwargs "{'from_date': '2026-08-01'}"
"""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.constants import IS_COD_CHECKBOX, ORDER_CODE_FIELD


def run(dry_run: bool = False, from_date: str | None = None, limit: int | None = None):
    if not frappe.db.exists("Custom Field", {"dt": "Sales Order", "fieldname": IS_COD_CHECKBOX}):
        print(f"{IS_COD_CHECKBOX} does not exist on Sales Order -- run "
              "alaiy_os_connector_unicommerce.setup.install.setup_custom_fields first.", flush=True)
        return

    from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
    from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order

    filters = {ORDER_CODE_FIELD: ["is", "set"], IS_COD_CHECKBOX: ["in", [0, None]]}
    if from_date:
        filters["transaction_date"] = [">=", from_date]

    orders = frappe.db.get_all(
        "Sales Order", filters=filters, fields=["name", ORDER_CODE_FIELD],
        order_by="transaction_date desc", limit=limit,
    )
    print(f"{len(orders)} Sales Orders with a blank COD flag", flush=True)
    if not orders:
        return

    client = UnicommerceClient()
    cod = prepaid = missing = failed = 0

    for i, order in enumerate(orders, 1):
        code = order[ORDER_CODE_FIELD]
        try:
            so_data = get_sales_order(client, code)
        except Exception:
            failed += 1
            continue

        if not so_data:
            # A failed fetch is NOT a prepaid order -- leaving the flag blank
            # keeps it eligible for a later re-run, where writing 0 would
            # silently bake in a wrong answer.
            missing += 1
            continue

        is_cod = bool(so_data.get("cod"))
        if is_cod:
            cod += 1
        else:
            prepaid += 1

        if not dry_run:
            # A submitted Sales Order cannot take a normal save; this is a
            # read-only reporting flag, so write the column directly.
            frappe.db.set_value("Sales Order", order["name"], IS_COD_CHECKBOX,
                                1 if is_cod else 0, update_modified=False)
            if i % 200 == 0:
                frappe.db.commit()
                print(f"  ...{i}/{len(orders)}", flush=True)

    if not dry_run:
        frappe.db.commit()

    print(f"{'would set' if dry_run else 'set'}: {cod} COD, {prepaid} prepaid; "
          f"{missing} not returned by Unicommerce, {failed} fetch errors", flush=True)
