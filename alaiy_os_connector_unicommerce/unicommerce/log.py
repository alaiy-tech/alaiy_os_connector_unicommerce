# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Error logging for the client -- plain frappe.log_error, same convention the
Shopify connector uses throughout. The upstream ecommerce_integrations app
writes one row per API error into its own "Ecommerce Integration Log"
doctype; this connector doesn't carry that doctype over, so per-call errors
go to the standard Error Log instead, and run-level status/counters live on
Unicommerce Sync Log (one row per sync run, not per API call).
"""

import frappe


def log_api_error(message: str, response_data=None):
    full_message = message
    if response_data is not None:
        full_message += f"\n\nResponse: {response_data}"
    frappe.log_error(title="Unicommerce API error", message=full_message[:100000])
