# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.order.test_tracking"""

import unittest

from alaiy_os_connector_unicommerce.unicommerce.constants import (
    SHIPPING_PROVIDER_CODE,
    TRACKING_CODE_FIELD,
    TRACKING_LINK_FIELD,
)
from alaiy_os_connector_unicommerce.unicommerce.order.tracking import package_tracking


class TestPackageTracking(unittest.TestCase):
    def test_maps_number_link_and_courier(self):
        values = package_tracking({"trackingNumber": "AWB1", "trackingLink": "https://t/AWB1", "shippingProvider": "BLUEDART"})
        self.assertEqual(values, {
            TRACKING_CODE_FIELD: "AWB1", TRACKING_LINK_FIELD: "https://t/AWB1", SHIPPING_PROVIDER_CODE: "BLUEDART",
        })

    def test_courier_falls_back_through_the_names_unicommerce_uses(self):
        self.assertEqual(package_tracking({"shippingProviderCode": "DTDC"})[SHIPPING_PROVIDER_CODE], "DTDC")
        self.assertEqual(package_tracking({"shippingCourier": "FEDEX"})[SHIPPING_PROVIDER_CODE], "FEDEX")

    def test_missing_values_stay_empty(self):
        self.assertEqual(package_tracking({}), {
            TRACKING_CODE_FIELD: None, TRACKING_LINK_FIELD: None, SHIPPING_PROVIDER_CODE: None,
        })
