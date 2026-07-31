"""
Import the whole Unicommerce catalogue into Alaiy OS Items.

Until now the only way an item arrived was as a side effect of importing an
order that referenced it (_sync_order_items), so anything never sold stayed
invisible. /services/rest/v1/product/itemType/search paginates the tenant's
full catalogue, which makes a real bulk import possible -- note it sits under
the /product/ prefix, not the /catalog/ one the existing get/createOrEdit
calls use.

Read-only against Unicommerce: search plus one get per new SKU. Nothing is
written back.

Reuses import_product_from_unicommerce per SKU rather than mapping the search
payload directly, so items land through exactly the same path (and the same
field mapping, brand handling and dedupe) as an order-driven import. Costs one
extra API call per new item, which is worth the consistency.

Run:
    # what's there, writes nothing
    bench --site <site> execute alaiy_os_connector_unicommerce.unicommerce.product.bulk_import.run

    # import everything missing
    bench --site <site> execute alaiy_os_connector_unicommerce.unicommerce.product.bulk_import.run --kwargs "{'dry_run': False}"

    # try a few first
    ... --kwargs "{'dry_run': False, 'limit': 20}"

    # one category, or only recently-changed items
    ... --kwargs "{'dry_run': False, 'category_code': 'BPC'}"
    ... --kwargs "{'dry_run': False, 'updated_since_hours': 24}"
"""

import time

import frappe

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.catalog import search_item_types
from alaiy_os_connector_unicommerce.unicommerce.constants import ITEM_EXTERNAL_ID_FIELD

_PAGE = 100
_PROGRESS_EVERY = 100


def _iter_catalogue(client, category_code=None, updated_since_hours=None, limit=None):
    """Walk every page of the catalogue, yielding each element."""
    start = 0
    seen = 0
    while True:
        elements, total = search_item_types(
            client, display_start=start, display_length=_PAGE,
            category_code=category_code, updated_since_hours=updated_since_hours)
        if not elements:
            return
        for el in elements:
            yield el, total
            seen += 1
            if limit and seen >= int(limit):
                return
        start += len(elements)
        if start >= total:
            return


def run(dry_run=True, limit=None, category_code=None, updated_since_hours=None):
    from alaiy_os_connector_unicommerce.unicommerce.product.pull import (
        import_product_from_unicommerce,
    )

    settings = frappe.get_single("Unicommerce Connector Settings")
    if not settings.is_enabled:
        print("[bulk_import] connector is disabled -- enable it first")
        return

    client = UnicommerceClient()
    started = time.monotonic()

    existing = created = failed = 0
    missing_skus = []
    total = 0

    for el, total in _iter_catalogue(client, category_code, updated_since_hours, limit):
        sku = el.get("skuCode")
        if not sku:
            continue
        if frappe.db.exists("Item", {ITEM_EXTERNAL_ID_FIELD: sku}) or frappe.db.exists("Item", sku):
            existing += 1
            continue
        missing_skus.append((sku, el.get("name") or ""))

    print(f"[bulk_import] catalogue: {total} items in Unicommerce")
    print(f"  already in Alaiy OS : {existing}")
    print(f"  missing locally     : {len(missing_skus)}")

    if dry_run:
        print("\n  first 20 missing:")
        for sku, name in missing_skus[:20]:
            print(f"    {sku!r:26} {name[:60]}")
        print("\n[bulk_import] DRY RUN -- nothing imported. "
              "Re-run with dry_run=False to create these Items.")
        return

    print(f"  started {frappe.utils.now()}\n")
    for i, (sku, name) in enumerate(missing_skus, 1):
        try:
            import_product_from_unicommerce(sku=sku, client=client)
            frappe.db.commit()
            created += 1
        except Exception:
            failed += 1
            frappe.db.rollback()
            frappe.log_error(title=f"[bulk_import] {sku} failed",
                             message=frappe.get_traceback())
            print(f"  [{i}/{len(missing_skus)}] FAILED {sku} -- see Error Log")

        if i % _PROGRESS_EVERY == 0 or i == len(missing_skus):
            elapsed = time.monotonic() - started
            rate = i / elapsed if elapsed else 0
            eta = (len(missing_skus) - i) / rate if rate else 0
            print(f"    -- {i}/{len(missing_skus)} in {elapsed / 60:.1f}m "
                  f"| created={created} failed={failed} | ETA {eta / 60:.1f}m")

    frappe.db.commit()
    print(f"\n[bulk_import] done in {(time.monotonic() - started) / 60:.1f}m")
    print(f"  created: {created}")
    print(f"  skipped (already present): {existing}")
    print(f"  failed : {failed}" + ("  <-- check Error Log" if failed else ""))
