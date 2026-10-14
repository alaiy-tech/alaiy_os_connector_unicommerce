# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Error logging for the client -- plain frappe.log_error, same convention the
Shopify connector uses throughout. The upstream ecommerce_integrations app
writes one row per API error into its own "Ecommerce Integration Log"
doctype; this connector doesn't carry that doctype over, so per-call errors
go to the standard Error Log instead, and run-level status/counters live on
Unicommerce Sync Log (one row per sync run, not per API call).

The scheduled jobs revisit the same failing records every run, so the same
error was being written thousands of times and buried every new one.
`log_once` writes a given error at most once per window, across every worker
process, and counts what it suppressed.
"""

import hashlib

import frappe

#: How long an identical error stays suppressed after it has been logged.
DEFAULT_WINDOW_SECONDS = 60 * 60


def log_once(title: str, message: str, key: str | None = None, window: int = DEFAULT_WINDOW_SECONDS) -> bool:
    """`frappe.log_error`, but not again for the same `key` within `window`
    seconds. The key defaults to the title. Returns whether a row was written.

    The suppression state lives in the site cache, so it holds across worker
    processes; if the cache is unavailable the error is logged rather than
    lost.
    """
    cache_key = "unicommerce_logged:" + hashlib.sha1((key or title).encode()).hexdigest()
    try:
        cache = frappe.cache()
        if cache.get_value(cache_key):
            return False
        cache.set_value(cache_key, 1, expires_in_sec=window)
    except Exception:
        pass
    frappe.log_error(title=title, message=message)
    return True


def _error_signature(message: str) -> str:
    """What makes two API errors "the same": the exception text for a
    traceback, the first line for anything else -- not the request body or
    ids further down, which differ on every call."""
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return ""
    return (lines[-1] if lines[0].startswith("Traceback") else lines[0])[:200]


def log_api_error(message: str, response_data=None):
    full_message = message
    if response_data is not None:
        full_message += f"\n\nResponse: {response_data}"
    log_once("Unicommerce API error", full_message[:100000], key="api:" + _error_signature(message))
