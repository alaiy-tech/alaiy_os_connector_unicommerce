# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Scheduler entry point. hooks.py runs check_and_enqueue() every minute; it
reads the configured intervals from Unicommerce Connector Settings and
enqueues a background job per sync type only when one is actually due.
"""

import frappe
from frappe.utils import now_datetime, add_to_date

# Both interval fields are Selects whose options are plain minute counts
# ("10", "15", "30", "60"), so the value is parsed rather than mapped -- an
# earlier hardcoded {"5 min": 5, ...} lookup table never matched a real
# option, which silently disabled every scheduled sync.
_MIN_INTERVAL_MINUTES = 1

# A sync that has been "running" longer than this is treated as dead, so a
# crashed job never blocks the schedule forever.
_STALE_RUNNING_SECONDS = 1800


def check_and_enqueue():
    if not frappe.db.exists("DocType", "Unicommerce Sync Log"):
        return

    settings = frappe.get_single("Unicommerce Connector Settings")
    if not settings.is_enabled:
        return

    _maybe_enqueue(
        interval_setting=settings.order_sync_frequency,
        sync_type="pull",
        enqueue_fn="alaiy_os_connector_unicommerce.unicommerce.sync.run_pull_sync",
    )
    # Item push has no interval field of its own, so it rides order_sync_frequency.
    # The toggle must be checked HERE: run_push_sync calls upload_new_items(force=True),
    # which deliberately bypasses its own is_enabled/upload_item_to_unicommerce guard
    # so the manual Force Sync button can override it. Without this check a scheduled
    # run would push items even with the setting off.
    if settings.upload_item_to_unicommerce:
        _maybe_enqueue(
            interval_setting=settings.order_sync_frequency,
            sync_type="push",
            enqueue_fn="alaiy_os_connector_unicommerce.unicommerce.sync.run_push_sync",
        )

    if settings.sync_purchase_orders:
        _maybe_enqueue(
            interval_setting=settings.po_sync_frequency,
            sync_type="purchase_order",
            enqueue_fn="alaiy_os_connector_unicommerce.unicommerce.sync.run_po_sync",
        )
        # GRN rides the same interval/toggle-gate as Purchase Orders (the
        # settings field description says so) but is its own sync_type/log
        # row -- a stuck or failed GRN run must not block PO sync, and vice
        # versa.
        if settings.sync_grn_receipts:
            _maybe_enqueue(
                interval_setting=settings.po_sync_frequency,
                sync_type="grn",
                enqueue_fn="alaiy_os_connector_unicommerce.unicommerce.sync.run_grn_sync",
            )


def _maybe_enqueue(interval_setting, sync_type, enqueue_fn):
    try:
        interval_minutes = int(interval_setting)
    except (TypeError, ValueError):
        return  # unset, "Disabled", or anything non-numeric
    if interval_minutes < _MIN_INTERVAL_MINUTES:
        return

    now = now_datetime()

    # Skip if a (non-stale) job is already running for this sync type.
    running = frappe.db.get_value(
        "Unicommerce Sync Log",
        {"sync_type": sync_type, "status": "running"},
        "started_at",
        order_by="started_at desc",
    )
    if running and (now - running).total_seconds() < _STALE_RUNNING_SECONDS:
        return

    # Skip if the last success is still inside the configured interval.
    last_success = frappe.db.get_value(
        "Unicommerce Sync Log",
        {"sync_type": sync_type, "status": "success"},
        "started_at",
        order_by="started_at desc",
    )
    if last_success and now < add_to_date(last_success, minutes=interval_minutes):
        return

    frappe.enqueue(enqueue_fn, queue="long", timeout=600, trigger="scheduled")
