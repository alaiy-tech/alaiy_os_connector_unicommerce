# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Reachability check for the saved credentials. Wired into the registry via
connector_meta["test_method"] and called by the "Test Connection" button.
Always returns {"success": bool, "message": str} -- never raises to the caller.
"""

import frappe


@frappe.whitelist()
def test_connection():
    settings = frappe.get_single("Unicommerce Connector Settings")

    if not settings.unicommerce_site:
        return {"success": False, "message": "Unicommerce Site is not set."}
    if not settings.username or not settings.get_password("password"):
        return {"success": False, "message": "Username/Password is not set."}

    try:
        settings.update_tokens(grant_type="password")
        settings.flags.ignore_permissions = True
        settings.save()
        return {"success": True, "message": f"Connected to {settings.unicommerce_site}."}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}
