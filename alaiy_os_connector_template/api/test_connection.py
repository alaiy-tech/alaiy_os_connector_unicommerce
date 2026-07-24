# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Reachability check for the saved credentials. Wired into the registry via
connector_meta["test_method"] and called by the "Test Connection" button.
Always returns {"success": bool, "message": str} — never raises to the caller.
"""

import frappe


@frappe.whitelist()
def test_connection():
    doc = frappe.get_single("Template Connector Settings")
    api_url = (doc.template_api_url or "").strip().rstrip("/")
    api_token = doc.get_password("template_api_token") if doc.template_api_token else None

    if not api_url:
        return {"success": False, "message": "API URL is not set."}
    if not api_token:
        return {"success": False, "message": "API Token is not set."}

    import requests

    # Point this at a lightweight, auth-required endpoint on your API.
    url = f"{api_url}/ping"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"success": True, "message": f"Connected successfully ({resp.status_code})"}
        elif resp.status_code == 401:
            return {"success": False, "message": "Authentication failed — check your API Token."}
        elif resp.status_code == 403:
            return {"success": False, "message": "Access forbidden — verify your credentials."}
        else:
            return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": f"Could not connect to {api_url}. Check the API URL."}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Request timed out (10s)."}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}
