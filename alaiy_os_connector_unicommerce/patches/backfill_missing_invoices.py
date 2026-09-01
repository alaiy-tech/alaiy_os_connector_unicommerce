# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
One-off: generate the Sales Invoices that were never created while the
Unicommerce API user was denied /invoice/details/get.

Invoice sync calls that endpoint for every shipping package. While it returned
403, _create_sales_invoices skipped the package and the order was left
uninvoiced -- silently, from the caller's point of view. The scheduled
hourly_long job only revisits RECENTLY updated orders, so once the permission
is restored it heals new orders but never goes back for the old ones. This
closes that window; it is not meant to run on a schedule.

Only COMPLETE orders are considered. A PROCESSING order is still in flight and
will invoice itself on the next scheduled tick; CREATED and
PENDING_VERIFICATION legitimately have no invoice yet.

MIND THE ACCOUNTING PERIOD. This creates backdated documents. Generating an
invoice into a month whose GST return is already filed can force an amendment,
so scope it to the current period unless finance has signed off on the older
one -- hence from_date/to_date being required rather than defaulted.

Usage:
    # preview, always do this first
    bench --site <site> execute \
        alaiy_os_connector_unicommerce.patches.backfill_missing_invoices.run \
        --kwargs "{'from_date': '2026-08-01', 'to_date': '2026-08-31', 'dry_run': True}"

    # then for real, in batches
    bench --site <site> execute \
        alaiy_os_connector_unicommerce.patches.backfill_missing_invoices.run \
        --kwargs "{'from_date': '2026-08-01', 'to_date': '2026-08-31', 'limit': 200}"
"""

import frappe


def _pending(from_date, to_date, limit):
    return frappe.db.sql("""
        select so.name, so.transaction_date, so.grand_total
        from `tabSales Order` so
        where so.unicommerce_order_code is not null
          and so.docstatus = 1
          and so.unicommerce_order_status = 'COMPLETE'
          and so.transaction_date between %(from_date)s and %(to_date)s
          and not exists (
              select 1 from `tabSales Invoice` si
              where si.unicommerce_order_code = so.unicommerce_order_code
                and si.is_return = 0
          )
        order by so.transaction_date
        {limit}
    """.format(limit=f"limit {int(limit)}" if limit else ""),
        {"from_date": from_date, "to_date": to_date}, as_dict=True)


def run(from_date: str, to_date: str, dry_run: bool = False, limit: int | None = None):
    """Generate invoices for COMPLETE orders in [from_date, to_date] that have none."""
    from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
    from alaiy_os_connector_unicommerce.unicommerce.fulfillment.invoice import bulk_generate_invoices

    orders = _pending(from_date, to_date, limit)
    total = sum(o.grand_total or 0 for o in orders)
    print(f"{len(orders)} COMPLETE orders with no invoice in {from_date}..{to_date} "
          f"(order value {total:,.2f})", flush=True)
    if not orders:
        return

    if dry_run:
        for o in orders[:20]:
            print(f"  {o.name}  {o.transaction_date}  {o.grand_total}", flush=True)
        if len(orders) > 20:
            print(f"  ... and {len(orders) - 20} more", flush=True)
        print("dry run -- nothing created", flush=True)
        return

    # bench execute runs outside a web request, so nothing sets frappe.local.lang;
    # money_in_words then looks up a Language doc named None and raises on every
    # currency-touching insert. Same guard as the returns backfill.
    frappe.local.lang = (frappe.local.lang
                         or frappe.db.get_single_value("System Settings", "language") or "en")

    client = UnicommerceClient()

    # bulk_generate_invoices already isolates per-order failures and logs them,
    # so a bad order cannot take the batch down. Chunked so a crash mid-run
    # leaves committed progress behind and the same call resumes where it
    # stopped -- the query only ever picks up orders that still have no invoice.
    CHUNK = 50
    for i in range(0, len(orders), CHUNK):
        batch = [o.name for o in orders[i:i + CHUNK]]
        try:
            bulk_generate_invoices(batch, client=client)
        except Exception:
            frappe.log_error(title="Unicommerce: invoice backfill batch failed",
                             message=frappe.get_traceback())
        frappe.db.commit()
        print(f"  ...{min(i + CHUNK, len(orders))}/{len(orders)}", flush=True)

    remaining = len(_pending(from_date, to_date, None))
    print(f"done -- {len(orders) - remaining} invoiced, {remaining} still without an invoice "
          f"(check Error Log for those)", flush=True)
