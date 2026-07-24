# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Thin HTTP client for the external API. Built from Unicommerce Connector
Settings so every caller shares one place to read credentials and add auth
headers. Replace the request helpers with whatever your API needs (REST,
GraphQL, ...).
"""

import requests
import frappe


class UnicommerceClient:
    def __init__(self):
        settings = frappe.get_single("Unicommerce Connector Settings")
        self.base_url = (settings.unicommerce_api_url or "").strip().rstrip("/")
        self.token = settings.get_password("unicommerce_api_token") if settings.unicommerce_api_token else None
        if not self.base_url or not self.token:
            raise RuntimeError("Unicommerce connector is not configured (API URL / Token missing).")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path, params=None, timeout=30):
        resp = requests.get(
            f"{self.base_url}/{path.lstrip('/')}",
            headers=self._headers(),
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def post(self, path, json=None, timeout=30):
        resp = requests.post(
            f"{self.base_url}/{path.lstrip('/')}",
            headers=self._headers(),
            json=json,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
