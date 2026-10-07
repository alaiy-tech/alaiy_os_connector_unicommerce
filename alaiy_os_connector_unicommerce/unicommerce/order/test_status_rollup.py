# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.order.test_status_rollup"""

import unittest

from alaiy_os_connector_unicommerce.unicommerce.order.status import _furthest_package


class TestFurthestPackage(unittest.TestCase):
    def pick(self, *statuses):
        return _furthest_package([{"code": f"P{i}", "status": s} for i, s in enumerate(statuses)])["status"]

    def test_result_does_not_depend_on_listing_order(self):
        self.assertEqual(self.pick("DELIVERED", "CANCELLED"), "DELIVERED")
        self.assertEqual(self.pick("CANCELLED", "DELIVERED"), "DELIVERED")
        self.assertEqual(self.pick("PICKING", "DELIVERED", "PACKED"), "DELIVERED")

    def test_returns_rank_above_delivery(self):
        self.assertEqual(self.pick("DELIVERED", "RETURNED"), "RETURNED")
        self.assertEqual(self.pick("RETURN_EXPECTED", "DELIVERED"), "RETURN_EXPECTED")

    def test_unranked_statuses_only_count_when_nothing_else_is_known(self):
        self.assertEqual(self.pick("SPLITTED", "PACKED"), "PACKED")
        self.assertEqual(self.pick("CANCELLED"), "CANCELLED")
