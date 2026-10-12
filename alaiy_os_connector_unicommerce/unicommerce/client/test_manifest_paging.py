# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.client.test_manifest_paging"""

import unittest
from unittest.mock import patch

from alaiy_os_connector_unicommerce.unicommerce.client.manifest import (
    SHIPPING_PACKAGE_PAGE_SIZE, search_shipping_packages,
)


class FakeClient:
    """Serves `total` packages, and rejects a page larger than the endpoint allows."""

    def __init__(self, total):
        self.total = total
        self.lengths = []

    def request(self, endpoint, body, headers):
        options = body["searchOptions"]
        self.lengths.append(options["displayLength"])
        if options["displayLength"] > 500:
            return None, False
        start = options["displayStart"]
        count = min(options["displayLength"], self.total - start)
        return {"totalRecords": self.total, "elements": [{"code": str(start + i)} for i in range(count)]}, True


class TestShippingPackagePaging(unittest.TestCase):
    def test_page_size_is_within_what_the_endpoint_accepts(self):
        self.assertLessEqual(SHIPPING_PACKAGE_PAGE_SIZE, 500)

    def test_every_package_is_returned_across_pages(self):
        client = FakeClient(total=1234)
        self.assertEqual(len(search_shipping_packages(client, facility_code="F")), 1234)

    def test_a_failed_request_is_logged_not_silent(self):
        client = FakeClient(total=10)
        with patch("alaiy_os_connector_unicommerce.unicommerce.client.manifest.SHIPPING_PACKAGE_PAGE_SIZE", 1000), \
                patch("alaiy_os_connector_unicommerce.unicommerce.client.manifest.frappe.log_error") as log:
            self.assertEqual(search_shipping_packages(client, facility_code="F"), [])
        log.assert_called_once()
