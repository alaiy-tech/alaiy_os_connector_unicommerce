# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""bench --site <site> run-tests --module alaiy_os_connector_unicommerce.unicommerce.order.test_details"""

import unittest

from alaiy_os_connector_unicommerce.unicommerce.order.details import (
    custom_field_defs,
    item_values,
    order_values,
    package_values,
)


class TestDetails(unittest.TestCase):
    def test_payment_and_hold_and_cancellations(self):
        values = order_values({
            "customerGSTIN": "27ABCDE1234F1Z5",
            "paymentDetail": [
                {"paymentMode": "COD", "transactionId": "T1", "amountPaid": 100},
                {"paymentMode": "COD", "transactionId": "T2", "amountPaid": 50},
            ],
            "saleOrderItems": [
                {"itemSku": "A", "statusCode": "CANCELLED", "cancellationReason": "out of stock"},
                {"itemSku": "B", "statusCode": "CREATED", "onHold": True},
            ],
        })
        self.assertEqual(values["unicommerce_customer_gstin"], "27ABCDE1234F1Z5")
        self.assertEqual(values["unicommerce_payment_mode"], "COD")
        self.assertEqual(values["unicommerce_payment_transactions"], "T1, T2")
        self.assertEqual(values["unicommerce_amount_paid"], 150)
        self.assertEqual(values["unicommerce_on_hold"], 1)
        self.assertEqual(values["unicommerce_cancelled_lines"], "A: out of stock")

    def test_empty_values_are_left_out_but_zero_checkboxes_are_kept(self):
        values = item_values({"giftWrap": False, "voucherCode": "", "discount": 0})
        self.assertNotIn("unicommerce_line_voucher_code", values)
        self.assertEqual(values["unicommerce_line_gift_wrap"], 0)
        self.assertEqual(values["unicommerce_line_discount"], 0)

    def test_package_extras(self):
        values = package_values({"trackingStatus": "IN_TRANSIT", "paymentReconciled": True, "podCode": "P1"})
        self.assertEqual(values["unicommerce_tracking_status"], "IN_TRANSIT")
        self.assertEqual(values["unicommerce_payment_reconciled"], 1)
        self.assertEqual(values["unicommerce_pod_code"], "P1")

    def test_serial_and_imei_read_either_payload_name(self):
        self.assertEqual(item_values({"itemDetailFields": [{"Imei": "1"}]})["unicommerce_line_item_details"], "Imei: 1")
        self.assertEqual(
            item_values({"itemDetailFields": None, "itemDetailFieldDTOList": [{"SerialNumber": "S1"}]})[
                "unicommerce_line_item_details"
            ],
            "SerialNumber: S1",
        )

    def test_odd_item_detail_shapes_do_not_break_the_order(self):
        for rows in (["Imei", "SerialNumber"], "Imei", {"Imei": "9"}, [None, 5], []):
            values = item_values({"itemDetailFieldDTOList": rows, "discount": 5})
            self.assertEqual(values["unicommerce_line_discount"], 5)
        self.assertEqual(item_values({"itemDetailFields": {"Imei": "9"}})["unicommerce_line_item_details"], "Imei: 9")
        self.assertNotIn("unicommerce_line_item_details", item_values({"itemDetailFieldDTOList": ["Imei"]}))

    def test_invoice_reference_and_pre_tax_price(self):
        self.assertEqual(package_values({"irn": "abc123"})["unicommerce_irn"], "abc123")
        self.assertEqual(
            item_values({"sellingPriceWithoutTaxesAndDiscount": 669.0})["unicommerce_line_price_before_tax_discount"], 669.0
        )
        self.assertEqual(order_values({"orderCategory": "B2C", "source": "FLIPKART"})["unicommerce_order_category"], "B2C")

    def test_every_field_has_a_definition(self):
        defs = custom_field_defs()
        for doctype in ("Sales Order", "Sales Order Item", "Sales Invoice"):
            names = [d["fieldname"] for d in defs[doctype]]
            self.assertEqual(len(names), len(set(names)), doctype)
        order_fields = [d["fieldname"] for d in defs["Sales Order"]]
        self.assertIn("unicommerce_customer_gstin", order_fields)
        self.assertIn("unicommerce_details_attempted_at", order_fields)
