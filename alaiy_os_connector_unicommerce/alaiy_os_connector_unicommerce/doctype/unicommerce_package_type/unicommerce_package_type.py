# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class UnicommercePackageType(Document):
    def validate(self):
        self._update_title()
        self._validate_sizes()

    def _update_title(self):
        self.title = f"{self.package_type}: {self.length}x{self.width}x{self.height}"

    def _validate_sizes(self):
        for field in ("length", "width", "height"):
            if cint(self.get(field)) <= 0:
                frappe.throw(frappe._("Positive value required for {0}").format(field))
