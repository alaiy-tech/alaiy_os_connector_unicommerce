# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
The actual sync work + the Unicommerce Sync Log lifecycle helpers every sync
shares. run_pull_sync / run_push_sync are the two example jobs; replace their
bodies with real logic but keep the log-create → running → success/failed
bookkeeping so the connector card and Logs list stay accurate.
"""

import frappe
from frappe.utils import now_datetime


def get_or_create_log(sync_type, trigger, log_name=None):
    """
    Return the Sync Log to use for this run. If log_name is given (the API
    layer pre-created it so it shows as 'queued' immediately) reuse it;
    otherwise create a fresh one. Newly created logs start as 'queued'.
    """
    if log_name and frappe.db.exists("Unicommerce Sync Log", log_name):
        return frappe.get_doc("Unicommerce Sync Log", log_name)

    log = frappe.new_doc("Unicommerce Sync Log")
    log.sync_type = sync_type
    log.trigger = trigger
    log.status = "queued"
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log


def _mark_running(log):
    log.status = "running"
    log.started_at = now_datetime()
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _mark_finished(log, status, error_message=None):
    log.status = status
    log.finished_at = now_datetime()
    if error_message:
        log.error_message = error_message[:2000]
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _run(sync_type, trigger, log_name, worker):
    log = get_or_create_log(sync_type, trigger, log_name)
    _mark_running(log)
    try:
        worker(log)
        _mark_finished(log, "success")
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(
            title=f"Unicommerce connector: {sync_type} sync failed",
            message=frappe.get_traceback(),
        )
        raise


def run_pull_sync(trigger="scheduled", log_name=None):
    """Pull new orders from Unicommerce into Alaiy OS -- the primary pull
    direction for this connector (items are push-only, see run_push_sync)."""
    def worker(log):
        from alaiy_os_connector_unicommerce.unicommerce.order.pull import sync_new_orders
        sync_new_orders(force=True)

    _run("pull", trigger, log_name, worker)


def run_push_sync(trigger="scheduled", log_name=None):
    """Push new/changed Items to Unicommerce."""
    def worker(log):
        from alaiy_os_connector_unicommerce.unicommerce.product.push import upload_new_items
        upload_new_items(force=True)

    _run("push", trigger, log_name, worker)


def run_po_sync(trigger="scheduled", log_name=None):
    """Pull new Purchase Orders from Unicommerce into Alaiy OS."""
    def worker(log):
        from alaiy_os_connector_unicommerce.unicommerce.purchase_order.pull import sync_purchase_orders
        sync_purchase_orders()

    _run("purchase_order", trigger, log_name, worker)


def run_grn_sync(trigger="scheduled", log_name=None):
    """Pull new GRNs (goods received against a PO) from Unicommerce into
    Alaiy OS Purchase Receipts."""
    def worker(log):
        from alaiy_os_connector_unicommerce.unicommerce.purchase_order.grn_pull import sync_grn_receipts
        sync_grn_receipts()

    _run("grn", trigger, log_name, worker)
