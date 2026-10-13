# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.api.test_nsm"""

import base64
import unittest
from unittest.mock import patch

import frappe

from alaiy_os_connector_unicommerce.api import nsm


class TestNsmAuth(unittest.TestCase):
    def setUp(self):
        frappe.local.response = frappe._dict()

    def _headers(self, value):
        return patch.object(nsm.frappe, "get_request_header", lambda name, *a, **k: value)

    def _conf(self, username="agreed-user", password="agreed-pass"):
        return patch.object(nsm.frappe, "conf", frappe._dict(
            unicommerce_nsm_username=username, unicommerce_nsm_password=password,
        ))

    def test_token_is_stable_and_depends_on_the_password(self):
        self.assertEqual(nsm.expected_token("u", "p"), nsm.expected_token("u", "p"))
        self.assertNotEqual(nsm.expected_token("u", "p"), nsm.expected_token("u", "other"))

    def test_right_credentials_get_the_token(self):
        basic = "Basic " + base64.b64encode(b"agreed-user:agreed-pass").decode()
        with self._conf(), self._headers(basic):
            nsm.oauth_token()
        self.assertEqual(frappe.local.response["status"], "SUCCESS")
        self.assertEqual(frappe.local.response["access_token"], nsm.expected_token("agreed-user", "agreed-pass"))

    def test_wrong_credentials_are_refused(self):
        basic = "Basic " + base64.b64encode(b"agreed-user:wrong").decode()
        with self._conf(), self._headers(basic):
            nsm.oauth_token()
        self.assertEqual(frappe.local.response["status"], "INVALID_CREDENTIALS")
        self.assertEqual(frappe.local.response["http_status_code"], 401)

    def test_nothing_is_accepted_until_credentials_are_configured(self):
        basic = "Basic " + base64.b64encode(b":").decode()
        with self._conf(None, None), self._headers(basic):
            nsm.oauth_token()
        self.assertEqual(frappe.local.response["status"], "INVALID_CREDENTIALS")

    def test_an_event_needs_the_token(self):
        with self._conf(), self._headers("not-the-token"), patch.object(nsm, "request_refresh") as refresh:
            nsm.delivered()
        self.assertEqual(frappe.local.response["status"], "Failed")
        refresh.assert_not_called()

    def test_an_event_with_the_token_triggers_a_refresh(self):
        token = nsm.expected_token("agreed-user", "agreed-pass")
        with self._conf(), self._headers(token), patch.object(nsm, "request_refresh") as refresh, \
                patch.object(nsm.frappe, "request", None):
            nsm.delivered()
        self.assertEqual(frappe.local.response["status"], "Success")
        refresh.assert_called_once()


if __name__ == "__main__":
    unittest.main()
