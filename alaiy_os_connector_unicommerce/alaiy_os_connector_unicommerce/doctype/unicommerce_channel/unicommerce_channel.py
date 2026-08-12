# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


# Same naming convention setup.create_channel_accounts.py uses when it
# bootstraps these placeholder accounts -- kept in one place so a rename on
# either side doesn't silently break the other.
_PLACEHOLDER_ACCOUNT_NAMES = {
    "igst_account": "Output Tax IGST",
    "cgst_account": "Output Tax CGST",
    "sgst_account": "Output Tax SGST",
    "ugst_account": "Output Tax UGST",
    "tcs_account": "TCS Payable",
    "cod_account": "COD Charges Collected",
    "gift_wrap_account": "Gift Wrap Charges Collected",
    "fnf_account": "Freight Charges Collected",
}


class UnicommerceChannel(Document):
    def validate(self):
        self._autofill_accounts()
        self._check_company()

    def _autofill_accounts(self):
        """Only ever fills a currently-blank field -- never overwrites a
        real choice already made. Silently no-ops if the placeholder
        account hasn't been created yet (create_channel_accounts.py) or if
        the company's abbr can't be resolved -- the mandatory-field
        validation below still catches that case with a clear error."""
        if not self.company:
            return
        abbr = frappe.get_cached_value("Company", self.company, "abbr")
        if not abbr:
            return

        for field, account_name in _PLACEHOLDER_ACCOUNT_NAMES.items():
            if self.get(field):
                continue
            full_name = f"{account_name} - {abbr}"
            if frappe.db.exists("Account", full_name):
                self.set(field, full_name)

        if not self.cost_center:
            default_cc = frappe.get_cached_value("Company", self.company, "cost_center")
            if default_cc:
                self.cost_center = default_cc

        if not self.cash_or_bank_account:
            default_cash = frappe.get_cached_value("Company", self.company, "default_cash_account")
            if default_cash:
                self.cash_or_bank_account = default_cash

    def _check_company(self):
        company_fields = {
            "warehouse": "Warehouse",
            "fnf_account": "Account",
            "cod_account": "Account",
            "gift_wrap_account": "Account",
            "igst_account": "Account",
            "cgst_account": "Account",
            "sgst_account": "Account",
            "ugst_account": "Account",
            "tcs_account": "Account",
            "cash_or_bank_account": "Account",
            "cost_center": "Cost Center",
        }
        for field, doctype in company_fields.items():
            if self.company != frappe.db.get_value(doctype, self.get(field), "company", cache=True):
                frappe.throw(
                    _("{0}: {1} does not belong to company {2}").format(doctype, self.get(field), self.company)
                )
