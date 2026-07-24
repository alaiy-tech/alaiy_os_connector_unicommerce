# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
The actual sync work + the Template Sync Log lifecycle helpers every sync
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
    if log_name and frappe.db.exists("Template Sync Log", log_name):
        return frappe.get_doc("Template Sync Log", log_name)

    log = frappe.new_doc("Template Sync Log")
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
            title=f"Template connector: {sync_type} sync failed",
            message=frappe.get_traceback(),
        )
        raise


def run_pull_sync(trigger="scheduled", log_name=None):
    """Pull data from the external API into Alaiy OS. TODO: implement."""
    def worker(log):
        # from alaiy_os_connector_template.template.client import TemplateClient
        # client = TemplateClient()
        # data = client.get("...")
        # ... upsert into ERPNext, updating log counters as you go ...
        pass

    _run("pull", trigger, log_name, worker)


def run_push_sync(trigger="scheduled", log_name=None):
    """Push Alaiy OS data out to the external API. TODO: implement."""
    def worker(log):
        pass

    _run("push", trigger, log_name, worker)
