# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Watches the order sync and says so when it stops being right.

Every 10 minutes `check` looks at two things and keeps the result in the site cache for the portal
to show (`HEALTH_KEY`):

  * the order pull: when it last finished successfully. A pull that is killed before it ends never
    records an end, and nothing else showed that no order had arrived for a day.
  * drift: once an hour, today's and yesterday's orders in Unicommerce against the portal's, matched
    by order code on any date. Orders created in the last few minutes are not counted.

When the site config lists `globali_alert_emails`, a new problem is also mailed once, and again only
if it is still there six hours later. Without that setting nothing is sent.
"""

import time

import frappe
from frappe.utils import add_days, getdate, nowdate

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.orders import search_sales_order
from alaiy_os_connector_unicommerce.unicommerce.constants import ORDER_CODE_FIELD, SETTINGS_DOCTYPE

HEALTH_KEY = "unicommerce:sync-health"
DRIFT_KEY = "unicommerce:sync-drift"
NOTIFIED_KEY = "unicommerce:sync-notified:"
HEALTH_TTL_SECONDS = 6 * 60 * 60
DRIFT_EVERY_SECONDS = 60 * 60
NOTIFY_AGAIN_SECONDS = 6 * 60 * 60

#: A pull that has not finished in this long is a problem; pulls are due every 30 minutes.
PULL_STALE_MINUTES = 90
#: Orders created in Unicommerce this recently are not expected in the portal yet.
GRACE_MINUTES = 30
#: Missing orders that count as drift: more than this many, or more than this share of the day.
DRIFT_MIN_ORDERS = 10
DRIFT_MIN_SHARE = 0.03


def check():
    """Scheduled entry point. Never raises: a watchdog that fails must not stop anything else."""
    try:
        if not frappe.get_cached_doc(SETTINGS_DOCTYPE).is_enabled:
            return
        problems = _pull_problems()
        drift = _drift()
        problems += drift.get("problems", [])
        health = {
            "checked_at": str(frappe.utils.now_datetime()),
            "problems": problems,
            "drift": {k: v for k, v in drift.items() if k != "problems"},
        }
        frappe.cache().set_value(HEALTH_KEY, health, expires_in_sec=HEALTH_TTL_SECONDS)
        _notify(problems)
    except Exception:
        frappe.log_error(title="Unicommerce watchdog failed", message=frappe.get_traceback())


def get_health() -> dict | None:
    """What the last check found, or None if it has not run (or its result has expired)."""
    return frappe.cache().get_value(HEALTH_KEY)


def _pull_problems() -> list[dict]:
    last = frappe.db.get_value(
        "Unicommerce Sync Log", {"sync_type": "pull", "status": "success"}, "finished_at", order_by="finished_at desc"
    )
    if not last:
        return [_problem("pull_never", "critical", "No order pull has ever finished",
                         "No successful order pull is recorded in the sync log.")]
    age = (frappe.utils.now_datetime() - last).total_seconds() / 60
    if age > PULL_STALE_MINUTES:
        return [_problem(
            "pull_stale", "critical",
            f"Orders have not been pulled for {_ago(age)}",
            f"The last order pull finished at {last}. New orders from Unicommerce are not arriving, so "
            "today's figures are behind. A pull that is killed before it ends never records success.",
        )]
    return []


def _drift() -> dict:
    cache = frappe.cache()
    last = cache.get_value(DRIFT_KEY)
    if last and time.time() - last.get("at", 0) < DRIFT_EVERY_SECONDS:
        return last["result"]
    result = _compare_recent()
    cache.set_value(DRIFT_KEY, {"at": time.time(), "result": result}, expires_in_sec=DRIFT_EVERY_SECONDS * 2)
    return result


def _compare_recent() -> dict:
    client = UnicommerceClient()
    today = getdate(nowdate())
    uc: dict[str, str] = {}
    searched = 0
    for day in (add_days(today, -1), today):
        elements = search_sales_order(client, from_date=f"{day} 00:00:00", to_date=f"{day} 23:59:59")
        if elements is None:
            continue
        searched += 1
        for e in elements:
            if e.get("code"):
                uc[e["code"]] = str(day)
    if searched < 2:
        return {"problems": [], "note": "Unicommerce could not be searched; drift not checked."}

    held = set(frappe.get_all(
        "Sales Order", filters={ORDER_CODE_FIELD: ("in", list(uc) or [""])}, pluck=ORDER_CODE_FIELD
    ))
    missing = [c for c in uc if c not in held]
    # An order that has just been created is not late yet: look again in the next check.
    recent = _recently_created(client, missing)
    missing = [c for c in missing if c not in recent]
    share = len(missing) / len(uc) if uc else 0.0
    problems = []
    if len(missing) > DRIFT_MIN_ORDERS or (missing and share > DRIFT_MIN_SHARE):
        problems.append(_problem(
            "orders_missing", "critical" if len(missing) > 3 * DRIFT_MIN_ORDERS else "warning",
            f"{len(missing)} Unicommerce orders from today or yesterday are not in the portal",
            f"Unicommerce lists {len(uc)} orders for these two days and the portal is missing "
            f"{len(missing)} ({share:.0%}). Compare with the Unicommerce Sync Log and Error Log.",
        ))
    return {"unicommerce": len(uc), "missing": len(missing), "sample": missing[:10], "problems": problems}


def _recently_created(client, codes: list[str]) -> set[str]:
    """Codes among `codes` whose order was created in Unicommerce within the grace period.

    One search over a short window rather than a fetch per order."""
    if not codes:
        return set()
    window = search_sales_order(client, updated_since=GRACE_MINUTES)
    if window is None:
        return set()
    wanted = set(codes)
    return {e.get("code") for e in window if e.get("code") in wanted and _created_recently(e)}


def _created_recently(element: dict) -> bool:
    created = element.get("created")
    if not isinstance(created, (int, float)):
        # Created time not given: treat as recent, since it was updated inside the grace period.
        return True
    return time.time() - created / 1000 < GRACE_MINUTES * 60


def _problem(key: str, severity: str, title: str, detail: str) -> dict:
    return {"key": key, "severity": severity, "title": title, "detail": detail}


def _ago(minutes: float) -> str:
    if minutes < 120:
        return f"{int(minutes)} minutes"
    if minutes < 48 * 60:
        return f"{int(minutes // 60)} hours"
    return f"{int(minutes // (24 * 60))} days"


def _notify(problems: list[dict]) -> None:
    recipients = frappe.conf.get("globali_alert_emails")
    if not recipients or not problems:
        return
    cache = frappe.cache()
    fresh = [p for p in problems if not cache.get_value(NOTIFIED_KEY + p["key"])]
    if not fresh:
        return
    for p in fresh:
        cache.set_value(NOTIFIED_KEY + p["key"], 1, expires_in_sec=NOTIFY_AGAIN_SECONDS)
    body = "<br><br>".join(f"<b>{p['title']}</b><br>{p['detail']}" for p in fresh)
    frappe.sendmail(
        recipients=recipients if isinstance(recipients, list) else [recipients],
        subject="Order sync needs attention", message=body,
    )
