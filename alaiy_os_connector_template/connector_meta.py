"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.

To spin up a new connector from this template, rename "template"/"Template"
throughout and point the *_method values at your own api functions.
"""

connector_meta = {
    "connector_id": "template",
    "connector_name": "Template",
    "connector_app": "alaiy_os_connector_template",
    # "channel" (sell TO — e.g. Shopify) or "supplier" (buy FROM — e.g. Cloudstore)
    "connector_type": "channel",
    "description": "Template connector — rename me",
    "icon": "box",
    "icon_url": "",
    "settings_doctype": "Template Connector Settings",
    "test_method": "alaiy_os_connector_template.api.test_connection.test_connection",
    # The registry exposes two sync "slots". Map them to whatever your
    # connector actually does; the labels are what the UI shows.
    "sync_categories_method": "alaiy_os_connector_template.api.sync.trigger_pull_sync",
    "sync_items_method": "alaiy_os_connector_template.api.sync.trigger_push_sync",
    "sync_status_method": "alaiy_os_connector_template.api.sync.get_sync_status",
    "sync_categories_label": "Pull",
    "sync_items_label": "Push",
    "is_enabled": 0,
    "connection_status": "untested",
}
