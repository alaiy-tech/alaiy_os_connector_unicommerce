# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Whitelisted entry points the Alaiy OS connector card and the settings form
call to kick off / inspect syncs. These stay thin: create the log so it shows
up as "queued" immediately, then enqueue the real work on the long queue.
"""

import frappe

from alaiy_os_connector_template.template.sync import get_or_create_log


@frappe.whitelist()
def trigger_pull_sync():
    """Manually enqueue a 'pull' sync (external → Alaiy OS)."""
    log = get_or_create_log("pull", "manual")
    frappe.enqueue(
        "alaiy_os_connector_template.template.sync.run_pull_sync",
        queue="long",
        timeout=600,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def trigger_push_sync():
    """Manually enqueue a 'push' sync (Alaiy OS → external)."""
    log = get_or_create_log("push", "manual")
    frappe.enqueue(
        "alaiy_os_connector_template.template.sync.run_push_sync",
        queue="long",
        timeout=600,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def get_sync_status(sync_type=None):
    """
    Return the most recent Template Sync Log rows, newest first.

    The Alaiy OS connector card passes the registry slot name ("categories"
    or "items"); map those to this connector's own sync_type values.
    """
    filters = {}
    if sync_type:
        type_map = {"categories": "pull", "items": "push"}
        filters["sync_type"] = type_map.get(sync_type, sync_type)
    return frappe.get_all(
        "Template Sync Log",
        filters=filters,
        fields=[
            "name", "sync_type", "trigger", "status",
            "started_at", "finished_at",
            "items_processed", "items_created", "items_updated", "items_failed",
            "pages_total", "pages_done",
            "error_message",
        ],
        order_by="started_at desc",
        limit=5,
    )
