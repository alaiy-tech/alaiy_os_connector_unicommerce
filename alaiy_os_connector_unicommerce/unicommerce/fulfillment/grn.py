# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Upload GRN (goods receipt) Stock Entries to Unicommerce as an auto-GRN CSV import job."""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import cint, getdate
from frappe.utils.csvutils import UnicodeWriter
from frappe.utils.file_manager import save_file

from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
from alaiy_os_connector_unicommerce.unicommerce.client.import_job import create_import_job
from alaiy_os_connector_unicommerce.unicommerce.constants import (
    GRN_STOCK_ENTRY_TYPE, ITEM_EXTERNAL_ID_FIELD, SETTINGS_DOCTYPE,
)
from alaiy_os_connector_unicommerce.unicommerce.utils import remove_non_alphanumeric_chars

CSV_HEADER_LINE = (
    "Vendor Code*,Vendor Invoice Number*,Purchase Order Code,Vendor Invoice Date*,Sku"
    " Code*,Qty*,Item Code,Item Details,Shelf Code,MRP,Unit Price,Manufacturing Date,Expiry date"
    " as dd/MM/yyyy,Vendor Batch Number\r\n"
)


@dataclass
class GRNItemRow:
    vendor_code: str
    vendor_invoice_number: str
    invoice_date: str
    sku: str
    qty: int
    item_code: str
    purchase_order: str = ""
    manufacturing_date: str = ""
    expiry_date: str = ""
    batch_number: str = ""
    shelf_code: str = ""
    item_details: str = ""
    mrp: str = 0.0
    unit_price: str = 0.0

    def get_ordered_fields(self):
        return [
            self.vendor_code, self.vendor_invoice_number, self.purchase_order, self.invoice_date,
            self.sku, self.qty, self.item_code, self.item_details, self.shelf_code, self.mrp,
            self.unit_price, self.manufacturing_date, self.expiry_date, self.batch_number,
        ]


def is_unicommerce_grn(stock_entry) -> bool:
    if stock_entry.stock_entry_type != GRN_STOCK_ENTRY_TYPE:
        return False

    grn_enabled = frappe.db.get_single_value(SETTINGS_DOCTYPE, "use_stock_entry_for_grn")
    if not grn_enabled:
        frappe.throw(
            _("Auto GRN not enabled in Unicommerce settings. Cannot use Stock Entry Type: {0}").format(
                GRN_STOCK_ENTRY_TYPE
            )
        )
    return True


def validate_stock_entry_for_grn(doc, method=None):
    stock_entry = doc
    if not is_unicommerce_grn(stock_entry):
        return

    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    if not settings.is_enabled:
        return

    get_facility_code(stock_entry, settings)


def get_facility_code(stock_entry, unicommerce_settings) -> str:
    """Validate the Stock Entry targets a single warehouse and return its facility code."""
    target_warehouses = {d.t_warehouse for d in stock_entry.items}
    if len(target_warehouses) > 1:
        frappe.throw(_("{0} only supports one target warehouse (unicommerce facility)").format(GRN_STOCK_ENTRY_TYPE))

    warehouse = next(iter(target_warehouses))
    facility = unicommerce_settings.get_erpnext_to_integration_wh_mapping(all_wh=True).get(warehouse)
    if not facility:
        frappe.throw(
            _("{0} warehouse does not have a Unicommerce facility mapped to it.").format(warehouse),
            title="Unmapped Unicommerce Facility",
        )
    return facility


def upload_grn(doc, method=None):
    stock_entry = doc
    if not is_unicommerce_grn(stock_entry):
        return

    settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    facility_code = get_facility_code(stock_entry, settings)
    csv_file = _prepare_grn_import_csv(doc)

    response = create_auto_grn_import(csv_file, facility_code=facility_code)
    if not response or not response.get("successful"):
        frappe.throw(
            _("GRN upload failed, Unicommerce reported errors.<br>{0}").format(
                "<br>".join((response or {}).get("errors") or [])
            )
        )

    errors = response.get("errors")
    if errors:
        frappe.msgprint(_("Partial success, unicommerce reported errors:<br>{0}").format("<br>".join(errors)))
    else:
        frappe.msgprint(
            _("Successfully queued GRN import to Unicommerce. Confirm the status on Import Log in Uniware."),
            title="Success",
        )


def _prepare_grn_import_csv(stock_entry) -> str:
    """Prepare a CSV file in the Unicommerce auto-GRN import format, attach it to the Stock
    Entry, and return the generated file's name."""
    rows = []
    vendor_code = frappe.db.get_single_value(SETTINGS_DOCTYPE, "vendor_code")

    for item in stock_entry.items:
        price = frappe.db.get_value("Item", item.item_code, "standard_rate") or ""
        invoice_date = _get_unicommerce_format_date(stock_entry.posting_date)

        batch_details = frappe.db.get_value(
            "Batch", item.batch_no, fieldname=["manufacturing_date", "expiry_date"], as_dict=True
        )
        manufacturing_date = _get_unicommerce_format_date(
            batch_details.manufacturing_date if batch_details else getdate()
        )
        expiry_date = _get_unicommerce_format_date(
            batch_details.expiry_date if batch_details else getdate("2099-01-01")
        )

        sku = frappe.db.get_value("Item", item.item_code, ITEM_EXTERNAL_ID_FIELD)
        if not sku:
            frappe.throw(_("Item {0} does not have an associated Unicommerce SKU.").format(item.item_code))

        rows.append(GRNItemRow(
            vendor_code=vendor_code,
            vendor_invoice_number=stock_entry.name,
            invoice_date=invoice_date,
            sku=sku,
            qty=cint(item.qty),  # implicitly rounds down
            item_code=sku,
            manufacturing_date=manufacturing_date,
            expiry_date=expiry_date,
            batch_number=item.batch_no,
            mrp=price,
            unit_price=price,
        ))

    file_name = remove_non_alphanumeric_chars(stock_entry.name)
    file = save_file(
        fname=f"GRN-{file_name}.csv", content=_get_csv_content(rows), dt=stock_entry.doctype, dn=stock_entry.name,
    )
    return file.file_name


def _get_csv_content(rows: list[GRNItemRow]) -> bytes:
    writer = UnicodeWriter()
    for row in rows:
        writer.writerow(row.get_ordered_fields())
    return (CSV_HEADER_LINE + writer.getvalue()).encode("utf-8")


def _get_unicommerce_format_date(date) -> str:
    return getdate(date).strftime("%d/%m/%Y") if date else ""


def create_auto_grn_import(csv_filename: str, facility_code: str, client=None):
    """Create a new Unicommerce import job for auto-GRN items."""
    if client is None:
        client = UnicommerceClient()
    return create_import_job(client, job_name="Auto GRN Items", csv_filename=csv_filename, facility_code=facility_code)


def prevent_grn_cancel(doc, method=None):
    if not is_unicommerce_grn(doc):
        return
    frappe.throw(
        _("This Stock Entry cannot be cancelled. To undo it, move the stock back and remove it from Unicommerce."),
        title="GRN Stock Entry cannot be cancelled",
    )
