# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Install / migrate plumbing shared by every Alaiy OS connector:

  after_install            -> one-time cleanup on `bench install-app`
  sync_connector_registry  -> (re)register in OS Connector Registry (every migrate)

Heavy setup (custom fields, price lists, ...) intentionally does NOT run on
migrate. It runs once, lazily, the first time the connector is enabled from
its settings form (see the doctype controller's _run_setup()), so installing
the app is cheap and non-destructive until an admin opts in.
"""

import json

import frappe


def after_install():
    """
    Called once after `bench install-app`. Clear any stale encrypted Password
    field that may have been written under a different site encryption key
    (e.g. from a prior failed install), which otherwise surfaces as a
    'Failed to decrypt key' error on first load.
    """
    for fieldname in ("password", "access_token", "refresh_token"):
        frappe.db.set_single_value("Unicommerce Connector Settings", fieldname, "")
    frappe.db.commit()


def sync_connector_registry():
    """
    Register or update this connector's row in alaiy_os's OS Connector Registry.
    Called from hooks.py -> after_migrate on every bench migrate. Idempotent.
    """
    _fix_settings_as_single()

    if not frappe.db.exists("DocType", "OS Connector Registry"):
        return

    from alaiy_os_connector_unicommerce.connector_meta import connector_meta

    connector_id = connector_meta["connector_id"]

    if frappe.db.exists("OS Connector Registry", connector_id):
        doc = frappe.get_doc("OS Connector Registry", connector_id)
    else:
        doc = frappe.new_doc("OS Connector Registry")

    # Fields owned by the running system, never overwritten from static meta.
    RUNTIME_FIELDS = {"connection_status", "last_tested_at"}

    if doc.is_new():
        for key, val in connector_meta.items():
            if hasattr(doc, key):
                doc.set(key, val)
        doc.insert(ignore_permissions=True)
    else:
        for key, val in connector_meta.items():
            if key not in RUNTIME_FIELDS and hasattr(doc, key):
                doc.set(key, val)
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    _update_alaiy_os_sidebar()


def _update_alaiy_os_sidebar():
    """
    Re-run alaiy_os's workspace/sidebar provisioning so this connector's Logs
    link and Connectors entry (settings button + card) appear right after it
    registers, instead of waiting for the next full bench migrate.
    """
    try:
        from alaiy_os.setup.install import (
            create_or_update_workspace_sidebar,
            create_or_update_os_settings_workspace,
            create_or_update_os_settings_workspace_sidebar,
        )
        create_or_update_workspace_sidebar()
        create_or_update_os_settings_workspace()
        create_or_update_os_settings_workspace_sidebar()
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="Unicommerce connector: sidebar update failed",
            message=frappe.get_traceback(),
        )


def _fix_settings_as_single():
    """
    Force issingle=1 on the settings doctype. Frappe does not auto-convert an
    existing DocType from table-based to Single via bench migrate, so patch it
    directly every deploy.
    """
    frappe.db.sql(
        "UPDATE `tabDocType` SET issingle=1 "
        "WHERE name='Unicommerce Connector Settings' AND issingle=0"
    )
    frappe.db.commit()


# ---------------------------------------------------------------------------
# First-enable setup (called from the settings controller, not on migrate)
# ---------------------------------------------------------------------------
def setup_custom_fields():
    """
    Add this connector's custom fields to ERPNext doctypes. Idempotent — safe
    to call on every enable/migrate. Section-break fields go through
    frappe's own create_custom_fields (handles insert_after/ordering across
    a whole doctype's fieldlist reliably); the plain fields on Item/Item
    Group use the lighter _ensure_custom_fields helper below since those are
    few and don't need sections.
    """
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    from alaiy_os_connector_unicommerce.unicommerce.constants import (
        ADDRESS_JSON_FIELD, CHANNEL_ID_FIELD, CUSTOMER_CODE_FIELD, FACILITY_CODE_FIELD,
        INVOICE_CODE_FIELD, IS_COD_CHECKBOX, MANIFEST_GENERATED_CHECK, ORDER_CODE_FIELD,
        ORDER_DISPLAY_CODE_FIELD, ORDER_INVOICE_STATUS_FIELD, ORDER_ITEM_BATCH_NO,
        ORDER_ITEM_CODE_FIELD, ORDER_STATUS_FIELD, PACKAGE_TYPE_FIELD,
        PICKLIST_ORDER_DETAILS_FIELD, RETURN_CODE_FIELD, SHIPPING_METHOD_FIELD,
        SHIPPING_PACKAGE_CODE_FIELD, SHIPPING_PACKAGE_STATUS_FIELD, SHIPPING_PROVIDER_CODE,
        TRACKING_CODE_FIELD, UNICOMMERCE_SHIPPING_ID,
    )

    item_fields = [
        {
            "fieldname": "unicommerce_external_id",
            "label": "Unicommerce External ID",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "item_code",
        },
        {
            "fieldname": "sync_to_unicommerce",
            "label": "Sync to Unicommerce",
            "fieldtype": "Check",
            "default": "0",
            "in_list_view": 1,
            "insert_after": "disabled",
            "description": "Include this Item in Unicommerce syncs.",
        },
        {
            "fieldname": "unicommerce_item_length",
            "label": "Length (Unicommerce)",
            "fieldtype": "Float",
            "insert_after": "weight_per_unit",
        },
        {
            "fieldname": "unicommerce_item_width",
            "label": "Width (Unicommerce)",
            "fieldtype": "Float",
            "insert_after": "unicommerce_item_length",
        },
        {
            "fieldname": "unicommerce_item_height",
            "label": "Height (Unicommerce)",
            "fieldtype": "Float",
            "insert_after": "unicommerce_item_width",
        },
        {
            "fieldname": "unicommerce_batch_group_code",
            "label": "Unicommerce Batch Group Code",
            "fieldtype": "Data",
            "insert_after": "unicommerce_item_height",
        },
        {
            "fieldname": "unicommerce_inventory_synced_on",
            "label": "Unicommerce Inventory Synced On",
            "fieldtype": "Datetime",
            "read_only": 1,
            "insert_after": "unicommerce_batch_group_code",
        },
    ]
    _ensure_custom_fields("Item", item_fields)

    item_group_fields = [
        {
            "fieldname": "unicommerce_product_category",
            "label": "Unicommerce Product Category",
            "fieldtype": "Data",
            "description": "Unicommerce category code this Item Group maps to.",
            "insert_after": "item_group_name",
        },
    ]
    _ensure_custom_fields("Item Group", item_group_fields)

    # Section-break groups for Sales Order / Sales Invoice / Delivery Note --
    # create these first so the fields below have somewhere to insert after.
    custom_sections = {
        "Sales Order": [
            dict(
                fieldname="unicommerce_section",
                label="Unicommerce Details",
                fieldtype="Section Break",
                insert_after="update_auto_repeat_reference",
                collapsible=1,
            ),
        ],
        "Sales Invoice": [
            dict(
                fieldname="unicommerce_section",
                label="Unicommerce Details",
                fieldtype="Section Break",
                insert_after="against_income_account",
                collapsible=1,
            ),
        ],
        "Delivery Note": [
            dict(
                fieldname="unicommerce_section",
                label="Unicommerce Details",
                fieldtype="Section Break",
                insert_after="instructions",
                collapsible=1,
            ),
        ],
    }

    custom_fields = {
        "Sales Order": [
            dict(fieldname=ORDER_CODE_FIELD, label="Unicommerce Order No.", fieldtype="Data",
                 insert_after="unicommerce_section", read_only=1, search_index=1),
            dict(fieldname=ORDER_DISPLAY_CODE_FIELD, label="Unicommerce Display Order No.", fieldtype="Data",
                 insert_after=ORDER_CODE_FIELD, read_only=1, search_index=1),
            dict(fieldname=CHANNEL_ID_FIELD, label="Unicommerce Channel", fieldtype="Link",
                 insert_after=ORDER_DISPLAY_CODE_FIELD, read_only=1, options="Unicommerce Channel", search_index=1),
            dict(fieldname=FACILITY_CODE_FIELD, label="Unicommerce Facility Code", fieldtype="Small Text",
                 insert_after=CHANNEL_ID_FIELD, read_only=1),
            dict(fieldname=ORDER_STATUS_FIELD, label="Unicommerce Order Status", fieldtype="Small Text",
                 insert_after=FACILITY_CODE_FIELD, read_only=1),
            dict(fieldname=ORDER_INVOICE_STATUS_FIELD, label="Unicommerce Invoice generation Status",
                 fieldtype="Small Text", insert_after=ORDER_STATUS_FIELD, read_only=1),
            dict(fieldname=PACKAGE_TYPE_FIELD, label="Unicommerce Package Type", fieldtype="Link",
                 options="Unicommerce Package Type", insert_after=ORDER_INVOICE_STATUS_FIELD, allow_on_submit=1),
        ],
        "Sales Order Item": [
            dict(fieldname=ORDER_ITEM_CODE_FIELD, label="Unicommerce Order Item Code", fieldtype="Data",
                 insert_after="item_code", read_only=1),
            dict(fieldname=ORDER_ITEM_BATCH_NO, label="Unicommerce Batch Code", fieldtype="Data",
                 insert_after=ORDER_ITEM_CODE_FIELD, read_only=1),
        ],
        "Customer": [
            dict(fieldname=ADDRESS_JSON_FIELD, label="Unicommerce raw billing address", fieldtype="Text",
                 insert_after="naming_series", read_only=1, hidden=1),
            dict(fieldname=CUSTOMER_CODE_FIELD, label="Unicommerce customer code", fieldtype="Data",
                 insert_after=ADDRESS_JSON_FIELD, read_only=1),
            dict(fieldname=IS_COD_CHECKBOX, label="Is COD?", fieldtype="Check",
                 insert_after=CUSTOMER_CODE_FIELD, read_only=1),
        ],
        "Sales Invoice": [
            dict(fieldname=ORDER_CODE_FIELD, label="Unicommerce Order No.", fieldtype="Data",
                 insert_after="unicommerce_section", read_only=1, search_index=1),
            dict(fieldname=ORDER_DISPLAY_CODE_FIELD, label="Unicommerce Display Order No.", fieldtype="Data",
                 insert_after=ORDER_CODE_FIELD, read_only=1, search_index=1),
            dict(fieldname=CHANNEL_ID_FIELD, label="Unicommerce Channel", fieldtype="Link",
                 insert_after=ORDER_DISPLAY_CODE_FIELD, read_only=1, options="Unicommerce Channel", search_index=1),
            dict(fieldname=FACILITY_CODE_FIELD, label="Unicommerce Facility Code", fieldtype="Small Text",
                 insert_after=CHANNEL_ID_FIELD, read_only=1),
            dict(fieldname=INVOICE_CODE_FIELD, label="Unicommerce Invoice Code", fieldtype="Data",
                 insert_after=FACILITY_CODE_FIELD, read_only=1, search_index=1),
            dict(fieldname=SHIPPING_PACKAGE_CODE_FIELD, label="Unicommerce Shipping Package Code",
                 fieldtype="Small Text", insert_after=INVOICE_CODE_FIELD, read_only=1),
            dict(fieldname=SHIPPING_PROVIDER_CODE, label="Unicommerce Shipping Provider", fieldtype="Small Text",
                 insert_after=SHIPPING_PACKAGE_CODE_FIELD, read_only=1),
            dict(fieldname=SHIPPING_METHOD_FIELD, label="Unicommerce Shipping Method", fieldtype="Small Text",
                 insert_after=SHIPPING_PROVIDER_CODE, read_only=1),
            dict(fieldname=TRACKING_CODE_FIELD, label="Unicommerce Tracking Code", fieldtype="Small Text",
                 insert_after=SHIPPING_METHOD_FIELD, read_only=1),
            dict(fieldname=SHIPPING_PACKAGE_STATUS_FIELD, label="Unicommerce Package Status",
                 fieldtype="Small Text", insert_after=TRACKING_CODE_FIELD, read_only=1),
            dict(fieldname=MANIFEST_GENERATED_CHECK, label="Manifest generated", fieldtype="Check",
                 insert_after=SHIPPING_PACKAGE_STATUS_FIELD, read_only=1),
            dict(fieldname=IS_COD_CHECKBOX, label="Is COD?", fieldtype="Check",
                 insert_after=MANIFEST_GENERATED_CHECK, read_only=1),
            dict(fieldname=RETURN_CODE_FIELD, label="Unicommerce Return Code", fieldtype="Small Text",
                 insert_after=IS_COD_CHECKBOX, read_only=1),
        ],
        "Delivery Note": [
            dict(fieldname=ORDER_CODE_FIELD, label="Unicommerce Order No", fieldtype="Data",
                 insert_after="unicommerce_section", read_only=1),
            dict(fieldname=ORDER_DISPLAY_CODE_FIELD, label="Unicommerce Display Order No.", fieldtype="Data",
                 insert_after=ORDER_CODE_FIELD, read_only=1),
            dict(fieldname=UNICOMMERCE_SHIPPING_ID, label="Unicommerce Shipment Id", fieldtype="Data",
                 insert_after=ORDER_DISPLAY_CODE_FIELD, read_only=1),
        ],
        "Pick List": [
            dict(fieldname=PICKLIST_ORDER_DETAILS_FIELD, label="Order Details", fieldtype="Table",
                 options="Pick List Unicommerce Order Detail"),
        ],
    }

    create_custom_fields(custom_sections, update=False)
    create_custom_fields(custom_fields, update=False)

    frappe.db.commit()


def _ensure_custom_fields(doctype, fields):
    for f in fields:
        key = f"{doctype}-{f['fieldname']}"
        if frappe.db.exists("Custom Field", key):
            # Keep the description in sync even for an existing field —
            # it's just documentation, safe to overwrite.
            if f.get("description"):
                frappe.db.set_value("Custom Field", key, "description", f["description"])
            continue
        cf = frappe.new_doc("Custom Field")
        cf.dt = doctype
        cf.fieldname = f["fieldname"]
        cf.label = f["label"]
        cf.fieldtype = f["fieldtype"]
        cf.insert_after = f.get("insert_after", "")
        cf.search_index = 1 if f.get("search_index") else 0
        cf.read_only = 1 if f.get("read_only") else 0
        cf.in_list_view = 1 if f.get("in_list_view") else 0
        cf.default = f.get("default")
        cf.description = f.get("description", "")
        cf.module = "Alaiy Os Connector Unicommerce"
        cf.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Reusable migration utilities (not called by default — here because every
# connector eventually needs them; wire them into sync_connector_registry as
# your schema evolves).
# ---------------------------------------------------------------------------
def _backfill_singles_defaults(doctype, fieldnames):
    """
    A field's `default` only applies to NEW documents. For a Single doctype's
    one pre-existing row, adding a field with a default later does not populate
    it — it reads back empty forever unless someone opens and saves the form.
    Backfill it here, once, idempotently.

    Checks row EXISTENCE in tabSingles rather than the value, because for a
    Check field "never set" and "explicitly 0" both read back as 0.
    """
    meta = frappe.get_meta(doctype)
    for fieldname in fieldnames:
        already_set = frappe.db.sql(
            "SELECT 1 FROM `tabSingles` WHERE doctype=%s AND field=%s LIMIT 1",
            (doctype, fieldname),
        )
        if already_set:
            continue
        field = meta.get_field(fieldname)
        if not field or field.default in (None, ""):
            continue
        frappe.db.set_single_value(doctype, fieldname, field.default)
    frappe.db.commit()


def _drop_orphaned_singles_value(doctype, fieldname):
    """
    Removing a field from a DocType's JSON doesn't clean up its old stored
    value on a site that already had one — it becomes an orphaned, invisible
    row in tabSingles. Delete it explicitly.
    """
    frappe.db.sql(
        "DELETE FROM `tabSingles` WHERE doctype=%s AND field=%s",
        (doctype, fieldname),
    )
    frappe.db.commit()


def _ensure_list_view_column(doctype, fieldname, label):
    """
    Once a doctype's `List View Settings` row exists (created the first time
    anyone customizes columns), it overrides the "show every in_list_view
    field automatically" default — a newly added in_list_view field then never
    appears until re-added by hand. Append our field to the customized set.
    """
    if not frappe.db.exists("List View Settings", doctype):
        return  # no customization yet — in_list_view alone is enough
    settings = frappe.get_doc("List View Settings", doctype)
    fields = json.loads(settings.fields or "[]")
    if any(f.get("fieldname") == fieldname for f in fields):
        return
    fields.append({"fieldname": fieldname, "label": label})
    settings.fields = json.dumps(fields)
    settings.save(ignore_permissions=True)
    frappe.db.commit()
