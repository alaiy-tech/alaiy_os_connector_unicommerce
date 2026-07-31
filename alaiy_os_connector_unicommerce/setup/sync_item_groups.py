# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Create Alaiy OS Item Groups from the categories used by the Unicommerce catalogue.

Unicommerce exposes no endpoint that lists categories -- `product/category/addOrEdit`
is a write. But `itemType/search` returns `categoryCode` and `categoryName` on every
element, so walking the catalogue is the way to enumerate them.

Each group is created with `unicommerce_product_category` set to the Unicommerce
code, which is exactly what `_resolve_item_group` (unicommerce/product/pull.py)
looks up when importing an item. Without these groups every imported item falls
back to the connector's default group.

Usage:
    bench --site <site> execute \
        alaiy_os_connector_unicommerce.setup.sync_item_groups.sync
    bench --site <site> execute \
        alaiy_os_connector_unicommerce.setup.sync_item_groups.sync \
        --kwargs "{'dry_run': False}"
"""

import frappe
from frappe.utils.nestedset import get_root_of

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.catalog import search_item_types
from alaiy_os_connector_unicommerce.unicommerce.constants import PRODUCT_CATEGORY_FIELD

PAGE_SIZE = 200


def collect_categories(client=None) -> dict[str, str]:
    """Walk the entire catalogue and return {categoryCode: categoryName}.

    Also reports how many items carry an image, since that decides whether
    image handling is worth building for this tenant at all.
    """
    client = client or UnicommerceClient()
    categories: dict[str, str] = {}
    seen = with_image = start = 0

    while True:
        elements, total = search_item_types(client, display_start=start, display_length=PAGE_SIZE)
        if not elements:
            break

        for element in elements:
            seen += 1
            if element.get("imageUrl"):
                with_image += 1
            code = element.get("categoryCode")
            if code:
                categories.setdefault(code, element.get("categoryName") or code)

        start += len(elements)
        print(f"  {seen}/{total} items | {len(categories)} categories | {with_image} with image", flush=True)
        if total and start >= total:
            break

    print(f"\n{seen} items, {with_image} with an image, {len(categories)} distinct categories")
    return categories


def sync(dry_run: bool = True):
    """Create one Item Group per Unicommerce category. Dry run by default."""
    categories = collect_categories()
    parent = get_root_of("Item Group")
    created = linked = already = 0

    for code, name in sorted(categories.items(), key=lambda pair: pair[1]):
        if frappe.db.exists("Item Group", {PRODUCT_CATEGORY_FIELD: code}):
            already += 1
            continue

        # A group may already exist under this name from another source. Attach
        # the code to it rather than creating a near-duplicate -- but only if it
        # isn't already claimed by a different Unicommerce category.
        existing = frappe.db.exists("Item Group", name)
        if existing and frappe.db.get_value("Item Group", existing, PRODUCT_CATEGORY_FIELD):
            print(f"  SKIP  {name!r} already linked to a different category code")
            continue

        action = "link" if existing else "create"
        print(f"  {'would ' + action if dry_run else action}: {name}  <- {code}")
        if dry_run:
            created += not existing
            linked += bool(existing)
            continue

        if existing:
            frappe.db.set_value("Item Group", existing, PRODUCT_CATEGORY_FIELD, code)
            linked += 1
        else:
            frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": name,
                    "parent_item_group": parent,
                    "is_group": 0,
                    PRODUCT_CATEGORY_FIELD: code,
                }
            ).insert(ignore_permissions=True)
            created += 1

    if not dry_run:
        frappe.db.commit()

    verb = "would create" if dry_run else "created"
    print(f"\n{verb}: {created}, linked to existing groups: {linked}, already mapped: {already}")
