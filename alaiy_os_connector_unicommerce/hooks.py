app_name = "alaiy_os_connector_unicommerce"
app_title = "Alaiy Os Connector Unicommerce"
app_publisher = "Alaiy"
app_description = "Unicommerce Connector for AlaiyOS"
app_email = "mail@alaiy.com"
app_license = "agpl-3.0"

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
# Every Alaiy OS connector runs on top of alaiy_os (registry, workspace,
# connector card) and erpnext (Item, Sales Order, Warehouse, ...).
required_apps = ["alaiy_os", "erpnext"]

# ---------------------------------------------------------------------------
# Installation / migration
# ---------------------------------------------------------------------------
# after_install runs once on `bench install-app`; after_migrate runs on every
# `bench migrate`. sync_connector_registry() (re)registers this connector in
# alaiy_os's OS Connector Registry and is idempotent, so it is safe on migrate.
after_install = [
    "alaiy_os_connector_unicommerce.setup.install.after_install"
]

after_migrate = [
    "alaiy_os_connector_unicommerce.setup.install.sync_connector_registry"
]

# ---------------------------------------------------------------------------
# Alaiy OS sidebar
# ---------------------------------------------------------------------------
# Register this connector's Sync Log under the Alaiy OS "Logs" sidebar section.
# alaiy_os reads this hook in create_or_update_workspace_sidebar().
alaiy_os_sidebar_log_items = [
    {
        "link_type": "DocType",
        "link_to": "Unicommerce Sync Log",
        "label": "Unicommerce Logs",
        "icon": "activity",
    }
]

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# The "* * * * *" job decides whether a full pull/push sync is due (and is
# tracked in Unicommerce Sync Log); the 5-minute jobs below are lighter,
# independent polls that run on their own fixed cadence like upstream did.
scheduler_events = {
    "cron": {
        "* * * * *": [
            "alaiy_os_connector_unicommerce.unicommerce.sync_jobs.check_and_enqueue"
        ],
        "*/5 * * * *": [
            "alaiy_os_connector_unicommerce.unicommerce.inventory.push.update_inventory_on_unicommerce",
            "alaiy_os_connector_unicommerce.unicommerce.fulfillment.delivery_note.prepare_delivery_note",
        ],
    },
    "hourly_long": [
        "alaiy_os_connector_unicommerce.unicommerce.order.status.update_sales_order_status",
        "alaiy_os_connector_unicommerce.unicommerce.order.status.update_shipping_package_status",
    ],
}

# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------
doc_events = {
    "Item": {
        "validate": [
            "alaiy_os_connector_unicommerce.unicommerce.product.validate.validate_item",
            "alaiy_os_connector_unicommerce.unicommerce.utils.validate_tax_template",
        ],
    },
    "Sales Order": {
        "on_update_after_submit": "alaiy_os_connector_unicommerce.unicommerce.order.shipping.update_shipping_info",
        "on_cancel": "alaiy_os_connector_unicommerce.unicommerce.order.status.ignore_pick_list_on_sales_order_cancel",
    },
    "Stock Entry": {
        "validate": "alaiy_os_connector_unicommerce.unicommerce.fulfillment.grn.validate_stock_entry_for_grn",
        "on_submit": "alaiy_os_connector_unicommerce.unicommerce.fulfillment.grn.upload_grn",
        "on_cancel": "alaiy_os_connector_unicommerce.unicommerce.fulfillment.grn.prevent_grn_cancel",
    },
    "Pick List": {
        "validate": "alaiy_os_connector_unicommerce.unicommerce.fulfillment.pick_list.validate",
    },
    "Sales Invoice": {
        "on_submit": "alaiy_os_connector_unicommerce.unicommerce.fulfillment.invoice.on_submit",
        "on_cancel": "alaiy_os_connector_unicommerce.unicommerce.fulfillment.invoice.on_cancel",
    },
}

# ---------------------------------------------------------------------------
# Client scripts
# ---------------------------------------------------------------------------
doctype_js = {
    "Sales Order": "public/js/unicommerce/sales_order.js",
    "Sales Invoice": "public/js/unicommerce/sales_invoice.js",
    "Item": "public/js/unicommerce/item.js",
    "Stock Entry": "public/js/unicommerce/stock_entry.js",
    "Pick List": "public/js/unicommerce/pick_list.js",
}
