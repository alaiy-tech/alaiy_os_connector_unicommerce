# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.test_log_once"""

import unittest
from unittest.mock import MagicMock, patch

from alaiy_os_connector_unicommerce.unicommerce import log


class _Cache:
    def __init__(self):
        self.store = {}

    def get_value(self, key):
        return self.store.get(key)

    def set_value(self, key, value, expires_in_sec=None):
        self.store[key] = value


class TestLogOnce(unittest.TestCase):
    def setUp(self):
        self.cache = _Cache()
        self.frappe = MagicMock()
        self.frappe.cache.return_value = self.cache
        self._patch = patch.object(log, "frappe", self.frappe)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_same_key_is_written_once(self):
        for _ in range(50):
            log.log_once("title", "message", key="k")
        self.assertEqual(self.frappe.log_error.call_count, 1)

    def test_different_keys_are_each_written(self):
        log.log_once("title", "message", key="a")
        log.log_once("title", "message", key="b")
        self.assertEqual(self.frappe.log_error.call_count, 2)

    def test_key_defaults_to_the_title(self):
        log.log_once("same", "first")
        log.log_once("same", "second")
        self.assertEqual(self.frappe.log_error.call_count, 1)

    def test_an_unavailable_cache_still_logs(self):
        self.frappe.cache.side_effect = RuntimeError("no cache")
        self.assertTrue(log.log_once("title", "message"))
        self.assertEqual(self.frappe.log_error.call_count, 1)

    def test_api_errors_with_different_request_bodies_collapse(self):
        for package in ("A1", "A2", "A3"):
            log.log_api_error(f"Invalid package\n\nURL: x\nbody: {package}")
        self.assertEqual(self.frappe.log_error.call_count, 1)

    def test_tracebacks_are_told_apart_by_their_exception(self):
        log.log_api_error("Traceback (most recent call last):\n  File x\nValueError: first")
        log.log_api_error("Traceback (most recent call last):\n  File y\nKeyError: second")
        self.assertEqual(self.frappe.log_error.call_count, 2)


if __name__ == "__main__":
    unittest.main()
