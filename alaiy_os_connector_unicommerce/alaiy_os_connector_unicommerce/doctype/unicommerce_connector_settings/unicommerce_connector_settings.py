# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime, now_datetime

from alaiy_os_connector_unicommerce.unicommerce.constants import GRN_STOCK_ENTRY_TYPE


class UnicommerceConnectorSettings(Document):
    def validate(self):
        # old_enabled is the last-committed DB value, so this comparison has
        # to run before the save overwrites it. Heavy setup runs only on the
        # 0 -> 1 transition, not on every save.
        old_enabled = frappe.db.get_single_value(
            "Unicommerce Connector Settings", "is_enabled"
        ) or 0
        self.flags.unicommerce_just_enabled = bool(self.is_enabled and not old_enabled)
        self.flags.unicommerce_just_disabled = bool(not self.is_enabled and old_enabled)
        self._sync_registry_is_enabled()

        if not self.is_enabled:
            self.access_token = ""
            self.refresh_token = ""
            self.token_type = ""
            self.expires_on = now_datetime()
            return

        self.validate_warehouse_mapping()
        self.validate_auto_grn_settings()
        if not self.access_token or now_datetime() >= get_datetime(self.expires_on):
            try:
                self.update_tokens()
            except Exception:
                frappe.log_error(
                    title="Unicommerce: failed to authenticate",
                    message=frappe.get_traceback(),
                )

    def on_update(self):
        # Deferred to on_update (after this row is written) so any code that
        # reads back the freshly saved credentials sees the new values.
        if self.flags.unicommerce_just_enabled:
            self._on_first_enable()
        elif self.flags.unicommerce_just_disabled:
            self._on_disable()

    def _on_first_enable(self):
        from alaiy_os_connector_unicommerce.setup.install import setup_custom_fields
        setup_custom_fields()

    def _on_disable(self):
        pass

    def _sync_registry_is_enabled(self):
        if frappe.db.exists("OS Connector Registry", "unicommerce"):
            frappe.db.set_value(
                "OS Connector Registry", "unicommerce", "is_enabled", self.is_enabled
            )

    # -----------------------------------------------------------------
    # OAuth token lifecycle
    # -----------------------------------------------------------------
    def renew_tokens(self, save=True):
        if now_datetime() >= get_datetime(self.expires_on):
            try:
                self.update_tokens()
            except Exception:
                frappe.log_error(title="Unicommerce: failed to authenticate", message=frappe.get_traceback())
                raise
        if save:
            self.flags.ignore_permissions = True
            self.save()
            frappe.db.commit()
            self.load_from_db()

    def update_tokens(self, grant_type="password"):
        url = f"https://{self.unicommerce_site}/oauth/token"
        params = {"grant_type": grant_type, "client_id": self.client_id}
        if grant_type == "password":
            params.update({"username": self.username, "password": self.get_password("password")})
        elif grant_type == "refresh_token":
            params.update({"refresh_token": self.get_password("refresh_token")})

        res = requests.get(url, params=params)
        if res.status_code == 200:
            data = res.json()
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
            self.token_type = data["token_type"]
            self.expires_on = add_to_date(now_datetime(), seconds=int(data["expires_in"]))
        else:
            data = res.json()
            error, description = data.get("error"), data.get("error_description")
            if error and "invalid_grant" in error:
                self._handle_refresh_token_expiry(grant_type=grant_type)
            else:
                frappe.throw(_("Unicommerce reported error: <br>{0}: {1}").format(error, description))

    def _handle_refresh_token_expiry(self, grant_type: str):
        """Refresh tokens expire every 30 days; only detectable via
        `invalid_grant` in the error message."""
        if grant_type == "password":
            return
        self.update_tokens(grant_type="password")

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------
    def validate_auto_grn_settings(self):
        if not self.use_stock_entry_for_grn:
            return
        if not self.vendor_code:
            frappe.throw(_("Vendor code required for Auto GRN upload."))
        if not frappe.db.exists("Stock Entry Type", GRN_STOCK_ENTRY_TYPE):
            entry_type = frappe.new_doc("Stock Entry Type")
            entry_type.name = GRN_STOCK_ENTRY_TYPE
            entry_type.purpose = "Material Transfer"
            entry_type.insert()
            entry_type.add_comment(text="Entry type used for Auto GRN on Unicommerce, do not modify.")

    def validate_warehouse_mapping(self):
        erpnext_whs = {wh_map.erpnext_warehouse for wh_map in self.warehouse_mapping}
        integration_whs = {wh_map.unicommerce_facility_code for wh_map in self.warehouse_mapping}
        if len(erpnext_whs) != len(integration_whs):
            frappe.throw(
                _("Warehouse Mapping should be unique and one-to-one without repeating the same warehouse.")
            )

    # -----------------------------------------------------------------
    # Warehouse mapping lookups
    # -----------------------------------------------------------------
    def get_erpnext_warehouses(self, all_wh=False) -> list:
        """Configured ERPNext warehouses. all_wh=True ignores enabled status."""
        return [wh_map.erpnext_warehouse for wh_map in self.warehouse_mapping if wh_map.enabled or all_wh]

    def get_erpnext_to_integration_wh_mapping(self, all_wh=False) -> dict:
        return {
            wh_map.erpnext_warehouse: wh_map.unicommerce_facility_code
            for wh_map in self.warehouse_mapping
            if wh_map.enabled or all_wh
        }

    def get_integration_to_erpnext_wh_mapping(self, all_wh=False) -> dict:
        reverse_map = self.get_erpnext_to_integration_wh_mapping(all_wh=all_wh)
        return {v: k for k, v in reverse_map.items()}

    def get_company_addresses(self, facility_code: str):
        """(billing_address, dispatch_address) mapped to a facility code."""
        for wh_map in self.warehouse_mapping:
            if wh_map.unicommerce_facility_code == facility_code:
                return wh_map.company_address, wh_map.dispatch_address
        return None, None
