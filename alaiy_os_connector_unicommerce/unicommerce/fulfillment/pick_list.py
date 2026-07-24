# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Track per-order pick status on Pick List as its rows get picked."""

import frappe
from frappe import _

from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD, PICKLIST_ORDER_DETAILS_FIELD, SETTINGS_DOCTYPE


def validate(self, method=None):
    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return

    sales_order = self.get("locations")[0].sales_order
    unicommerce_order_code = frappe.db.get_value("Sales Order", sales_order, ORDER_CODE_FIELD)
    if not unicommerce_order_code or not self.get("locations"):
        return

    for row in self.get("locations"):
        if row.picked_qty and float(row.picked_qty) > 0:
            if row.picked_qty > row.qty:
                row.picked_qty = row.qty
                frappe.throw(_("Row {0} Picked Qty cannot be more than Sales Order Qty").format(row.idx))
        if row.picked_qty == 0 and row.docstatus == 1:
            frappe.throw(_("You have not picked {0} in row {1}. Pick the item to proceed!").format(row.item_code, row.idx))

    unique_so_list = []
    for row in self.get("locations"):
        if row.sales_order not in unique_so_list:
            unique_so_list.append(row.sales_order)

    existing_so_list = [d.sales_order for d in self.get(PICKLIST_ORDER_DETAILS_FIELD)]
    for so in unique_so_list:
        if so not in existing_so_list:
            self.append(PICKLIST_ORDER_DETAILS_FIELD, {"sales_order": so})

        total = fully_picked = partial_picked = 0
        for item in self.get("locations"):
            if item.sales_order != so:
                continue
            total += 1
            if item.picked_qty == item.qty:
                fully_picked += 1
            elif int(item.picked_qty) > 0:
                partial_picked += 1

        if fully_picked == total:
            status = "Fully Picked"
        elif fully_picked == 0 and partial_picked == 0:
            status = ""
        else:
            status = "Partially Picked"

        for row in self.get(PICKLIST_ORDER_DETAILS_FIELD):
            if row.sales_order == so:
                row.pick_status = status
