# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
import unittest

from alaiy_os_connector_unicommerce.unicommerce.order.cancellation import _returned_share


class TestReturnedShare(unittest.TestCase):
    def test_whole_line_returned(self):
        # Two lines carry 30 and 70 of tax; only the second comes back.
        self.assertAlmostEqual(_returned_share({"a": 30.0, "b": 70.0}, {"b": 1.0}), 0.7)

    def test_nothing_returned_from_a_line(self):
        self.assertAlmostEqual(_returned_share({"a": 30.0, "b": 70.0}, {"a": 1.0}), 0.3)

    def test_all_returned(self):
        self.assertAlmostEqual(_returned_share({"a": 30.0, "b": 70.0}, {"a": 1.0, "b": 1.0}), 1.0)

    def test_no_tax_to_split(self):
        self.assertIsNone(_returned_share({}, {"a": 1.0}))
        self.assertIsNone(_returned_share({"a": 0.0}, {"a": 1.0}))
