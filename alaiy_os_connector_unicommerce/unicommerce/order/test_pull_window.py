# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.order.test_pull_window"""

import unittest
from datetime import datetime, timedelta

from alaiy_os_connector_unicommerce.unicommerce.order.pull import FULL_WINDOW_MINUTES, _changed_since_minutes


class TestChangedSinceMinutes(unittest.TestCase):
    now = datetime(2026, 10, 7, 12, 0, 0)

    def test_no_previous_run_covers_the_full_window(self):
        self.assertEqual(_changed_since_minutes(None, self.now), FULL_WINDOW_MINUTES)

    def test_recent_run_covers_elapsed_time_plus_buffer(self):
        self.assertEqual(_changed_since_minutes(self.now - timedelta(minutes=5), self.now), 15)
        self.assertEqual(_changed_since_minutes(self.now - timedelta(minutes=30), self.now), 40)

    def test_very_recent_run_never_goes_below_the_floor(self):
        self.assertEqual(_changed_since_minutes(self.now - timedelta(seconds=10), self.now), 15)

    def test_old_or_future_previous_run_covers_the_full_window(self):
        self.assertEqual(_changed_since_minutes(self.now - timedelta(days=3), self.now), FULL_WINDOW_MINUTES)
        self.assertEqual(_changed_since_minutes(self.now + timedelta(minutes=5), self.now), FULL_WINDOW_MINUTES)
