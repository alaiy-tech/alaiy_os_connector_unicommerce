# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Push ERPNext warehouse-wise stock levels to Unicommerce."""

from collections import defaultdict

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Max, Sum
from frappe.utils import cint, now
from frappe.utils.nestedset import get_descendants_of

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.inventory import bulk_inventory_update
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    INVENTORY_SYNCED_ON_FIELD, ITEM_EXTERNAL_ID_FIELD, ITEM_SYNC_CHECKBOX, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.utils import need_to_run

# Note: undocumented but currently handles ~1000 inventory changes in one
# request. The remainder is left to be picked up on the next interval.
MAX_INVENTORY_UPDATE_IN_REQUEST = 1000


def update_inventory_on_unicommerce(client=None, force: bool = False):
    """Push ERPNext warehouse-wise inventory to Unicommerce. Called by the
    scheduler on the configured interval; force=True ignores the interval."""
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled or not settings.enable_inventory_sync:
        return

    if not force and not need_to_run(SETTINGS_DOCTYPE, "inventory_sync_frequency", "last_inventory_sync"):
        return

    warehouses = settings.get_erpnext_warehouses()
    wh_to_facility_map = settings.get_erpnext_to_integration_wh_mapping()

    if client is None:
        client = UnicommerceClient()

    # tracks whether every warehouse push succeeded, per Item
    success_map: dict[str, bool] = defaultdict(lambda: True)
    inventory_synced_on = now()

    for warehouse in warehouses:
        is_group_warehouse = cint(frappe.db.get_value("Warehouse", warehouse, "is_group"))

        if is_group_warehouse:
            erpnext_inventory = _get_inventory_levels_of_group_warehouse(warehouse)
        else:
            erpnext_inventory = _get_inventory_levels((warehouse,))

        if not erpnext_inventory:
            continue

        erpnext_inventory = erpnext_inventory[:MAX_INVENTORY_UPDATE_IN_REQUEST]

        # TODO: consider reserved qty on both platforms.
        inventory_map = {d.unicommerce_sku: cint(d.actual_qty) for d in erpnext_inventory}
        facility_code = wh_to_facility_map[warehouse]

        response, status = bulk_inventory_update(client, facility_code=facility_code, inventory_map=inventory_map)

        if status:
            sku_to_item_map = {d.unicommerce_sku: d.item_code for d in erpnext_inventory}
            for sku, item_status in response.items():
                item_code = sku_to_item_map[sku]
                # any one warehouse sync failure marks the whole Item as failed
                success_map[item_code] = success_map[item_code] and item_status

    _update_inventory_sync_status(success_map, inventory_synced_on)


def _get_inventory_levels(warehouses: tuple):
    """Items with a Bin more recently modified than their last inventory
    sync, for the given warehouses."""
    Item = DocType("Item")
    Bin = DocType("Bin")

    query = (
        frappe.qb.from_(Item)
        .join(Bin)
        .on(Item.item_code == Bin.item_code)
        .select(
            Item.name.as_("item_code"),
            Item[ITEM_EXTERNAL_ID_FIELD].as_("unicommerce_sku"),
            Bin.actual_qty,
            Bin.warehouse,
            Bin.reserved_qty,
        )
        .where(
            (Bin.warehouse.isin(warehouses))
            & (Bin.modified > Item[INVENTORY_SYNCED_ON_FIELD])
            & (Item[ITEM_SYNC_CHECKBOX] == 1)
        )
    )
    return query.run(as_dict=1)


def _get_inventory_levels_of_group_warehouse(warehouse: str):
    """Same as _get_inventory_levels but consolidates all leaf warehouses
    under a group warehouse mapped to a single Unicommerce facility."""
    child_warehouses = get_descendants_of("Warehouse", warehouse)
    all_warehouses = (*tuple(child_warehouses), warehouse)

    Item = DocType("Item")
    Bin = DocType("Bin")

    query = (
        frappe.qb.from_(Item)
        .join(Bin)
        .on(Item.item_code == Bin.item_code)
        .select(
            Item.name.as_("item_code"),
            Item[ITEM_EXTERNAL_ID_FIELD].as_("unicommerce_sku"),
            Sum(Bin.actual_qty).as_("actual_qty"),
            Sum(Bin.reserved_qty).as_("reserved_qty"),
            Max(Bin.modified).as_("last_updated"),
            Max(Item[INVENTORY_SYNCED_ON_FIELD]).as_("last_synced"),
        )
        .where((Bin.warehouse.isin(all_warehouses)) & (Item[ITEM_SYNC_CHECKBOX] == 1))
        .groupby(Item.item_code)
        .having(Max(Bin.modified) > Max(Item[INVENTORY_SYNCED_ON_FIELD]))
    )

    data = query.run(as_dict=1)
    for item in data:
        item.warehouse = warehouse
    return data


def _update_inventory_sync_status(item_success_map: dict[str, bool], timestamp: str) -> None:
    for item_code, status in item_success_map.items():
        if status:
            frappe.db.set_value("Item", item_code, INVENTORY_SYNCED_ON_FIELD, timestamp)
