# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Thin wrapper around Unicommerce's REST API -- auth + one shared request()
call every domain module (catalog, orders, inventory, ...) builds on.
Domain-specific endpoint methods live in their own sibling modules, not on
this class -- same split as the Shopify connector's graphql_client.py
(generic transport) vs its queries.py/product/order packages (what to ask
for).

API docs: https://documentation.unicommerce.com/
"""

from typing import Any

import frappe
import requests
from frappe.utils import cstr

JsonDict = dict[str, Any]


class UnicommerceClient:
    def __init__(self, url: str | None = None, access_token: str | None = None):
        self.settings = frappe.get_single("Unicommerce Connector Settings")
        self.base_url = url or f"https://{self.settings.unicommerce_site}"
        self.access_token = access_token
        self._initialize_auth()

    def _initialize_auth(self):
        if not self.access_token:
            self.settings.renew_tokens()
            self.access_token = self.settings.get_password("access_token")
        self._auth_headers = {"Authorization": f"Bearer {self.access_token}"}

    def _refresh_auth(self):
        """Fetch a fresh access token after a 401 and rebuild the auth header."""
        self.settings.update_tokens(grant_type="refresh_token")
        self.access_token = self.settings.access_token
        self._auth_headers = {"Authorization": f"Bearer {self.access_token}"}

        # Persisting the token (to share it with other clients) is best-effort:
        # a persist failure must not block the retry, which already has the new
        # token in-memory. Reuses the doctype's own _save_retry_once (built for
        # exactly this race -- two concurrent clients each refreshing against
        # their own in-memory copy) instead of a raw save(), which had no
        # retry and was confirmed live to fail with TimestampMismatchError on
        # every collision (2,000+ occurrences).
        try:
            self.settings._save_retry_once()
        except Exception:
            frappe.log_error("Unicommerce: failed to persist refreshed access token")

    def request(
        self,
        endpoint: str,
        method: str = "POST",
        headers: JsonDict | None = None,
        body: JsonDict | None = None,
        params: JsonDict | None = None,
        files: JsonDict | None = None,
        log_error: bool = True,
    ) -> tuple[JsonDict, bool]:
        if headers is None:
            headers = {}
        headers.update(self._auth_headers)
        url = self.base_url + endpoint

        try:
            response = requests.request(
                url=url, method=method, headers=headers, json=body, params=params, files=files
            )
            # Token expired mid-run -> refresh once and retry the call.
            # File uploads are NOT retried: `requests` has already streamed
            # the file object into the first request's body, so the handle
            # is at EOF and replaying it would silently send an empty body.
            # Such calls fall through and fail loudly instead, so the upload
            # can be re-run intact.
            if response.status_code == 401 and not files:
                self._refresh_auth()
                headers.update(self._auth_headers)
                response = requests.request(
                    url=url, method=method, headers=headers, json=body, params=params, files=files
                )
            # Unicommerce puts useful detail in response text -- surface it in error logs.
            response.reason = cstr(response.reason) + cstr(response.text)
            response.raise_for_status()
        except Exception:
            if log_error:
                from alaiy_os_connector_unicommerce.unicommerce.log import log_api_error
                log_api_error(frappe.get_traceback())
            return None, False

        if method == "GET" and "application/json" not in (response.headers.get("content-type") or ""):
            return response.content, True

        data = frappe._dict(response.json())
        status = data.successful if data.successful is not None else True

        if not status:
            from alaiy_os_connector_unicommerce.unicommerce.log import log_api_error
            req = response.request
            request_data = "\n\n".join([f"URL: {req.url}", f"body: {req.body.decode('utf-8')}"])
            message = ", ".join(cstr(error["message"]) for error in data.errors)
            log_api_error(f"{message}\n\n{request_data}", response_data=data)

        return data, status
