# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
import time
import unittest

from alaiy_os_connector_unicommerce.unicommerce import watchdog


class TestWatchdogHelpers(unittest.TestCase):
    def test_age_wording(self):
        self.assertEqual(watchdog._ago(45), "45 minutes")
        self.assertEqual(watchdog._ago(300), "5 hours")
        self.assertEqual(watchdog._ago(3 * 24 * 60), "3 days")

    def test_created_recently(self):
        now_ms = time.time() * 1000
        self.assertTrue(watchdog._created_recently({"created": now_ms - 60_000}))
        self.assertFalse(watchdog._created_recently({"created": now_ms - 3 * 60 * 60_000}))
        # No created time: it was updated inside the grace period, so it counts as recent.
        self.assertTrue(watchdog._created_recently({}))
