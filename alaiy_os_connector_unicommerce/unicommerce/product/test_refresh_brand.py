# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.product.test_refresh_brand"""

import unittest
from unittest.mock import MagicMock, patch

from alaiy_os_connector_unicommerce.unicommerce.product import refresh_brand as rb


class _Cache:
    def __init__(self):
        self.store = {}

    def get_value(self, key):
        return self.store.get(key)

    def set_value(self, key, value, expires_in_sec=None):
        self.store[key] = value


class TestFillMissingBrands(unittest.TestCase):
    def setUp(self):
        self.cache = _Cache()
        self.frappe = MagicMock()
        self.frappe.cache.return_value = self.cache
        self.frappe.get_cached_doc.return_value = MagicMock(is_enabled=1)
        self.frappe.db.exists.return_value = True
        # First call lists blank-brand SKUs; the per-SKU lookup of items returns one name each.
        self.frappe.get_all.side_effect = lambda doctype, **kw: (
            ["SKU1", "SKU2"] if kw.get("pluck") == rb.ITEM_EXTERNAL_ID_FIELD else [kw["filters"][rb.ITEM_EXTERNAL_ID_FIELD]]
        )
        self.patches = [
            patch.object(rb, "frappe", self.frappe),
            patch.object(rb, "UnicommerceClient", MagicMock()),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _uc(self, brands):
        return patch.object(rb, "get_unicommerce_item", lambda client, sku: {"itemTypeDTO": {"brand": brands.get(sku)}})

    def test_fills_only_the_items_unicommerce_has_a_brand_for(self):
        with self._uc({"SKU1": "Kashmir Box", "SKU2": None}):
            out = rb.fill_missing_brands()
        self.assertEqual(out["filled"], 1)
        self.frappe.db.set_value.assert_called_once_with("Item", "SKU1", "brand", "Kashmir Box")

    def test_an_item_with_no_brand_upstream_is_not_asked_about_again_today(self):
        with self._uc({}):
            rb.fill_missing_brands()
            self.assertIn(f"{rb.CHECKED_KEY}:SKU1", self.cache.store)
            out = rb.fill_missing_brands()
        self.assertEqual(out["checked"], 0)

    def test_a_disabled_connector_does_nothing(self):
        self.frappe.get_cached_doc.return_value = MagicMock(is_enabled=0)
        self.assertEqual(rb.fill_missing_brands(), {"skipped": "connector disabled"})


if __name__ == "__main__":
    unittest.main()
