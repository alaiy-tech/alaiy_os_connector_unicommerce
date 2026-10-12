# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.fulfillment.test_delivery_note_states"""

import unittest

from alaiy_os_connector_unicommerce.unicommerce.fulfillment.delivery_note import is_shipped


class TestIsShipped(unittest.TestCase):
    def test_every_status_from_dispatch_onwards_is_shipped(self):
        for status in ("DISPATCHED", "SHIPPED", "DELIVERED", "RETURN_EXPECTED", "RETURNED", "RETURN_ACKNOWLEDGED"):
            self.assertTrue(is_shipped(status), status)

    def test_nothing_before_dispatch_is_shipped(self):
        for status in ("CREATED", "PICKING", "PICKED", "PACKED", "READY_TO_SHIP", "MANIFESTED"):
            self.assertFalse(is_shipped(status), status)

    def test_cancelled_and_unknown_are_not_shipped(self):
        for status in ("CANCELLED", "LOCATION_NOT_SERVICEABLE", "", None):
            self.assertFalse(is_shipped(status), repr(status))
