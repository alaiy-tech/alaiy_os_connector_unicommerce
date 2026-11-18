"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.
"""

# Columns of Unicommerce Sync Log, named the way the Connector Health page reads them.
_LOG_FIELDS = {
    "processed": "items_processed",
    "changed": ["items_created", "items_updated"],
    "failed": "items_failed",
    "error": "error_message",
}


def _health(key, label, sync_type, interval_setting, direction="pull"):
    # Each of these can legitimately have nothing to do, so zero-row runs are not a warning.
    return {
        "key": key,
        "label": label,
        "direction": direction,
        "log_doctype": "Unicommerce Sync Log",
        "log_filter": {"sync_type": sync_type},
        "fields": _LOG_FIELDS,
        "interval_setting": interval_setting,
        "interval_unit": "min",
        "scheduled": True,
        "expects_rows": False,
    }


connector_meta = {
    "connector_id": "unicommerce",
    "connector_name": "Unicommerce",
    "connector_app": "alaiy_os_connector_unicommerce",
    # "channel" (sell TO — e.g. Shopify) or "supplier" (buy FROM — e.g. Cloudstore)
    "connector_type": "supplier",
    "description": "Unicommerce WMS/OMS connector",
    "icon": "box",
    "icon_url": "/assets/alaiy_os_connector_unicommerce/images/unicommerce-icon.svg",
    "settings_doctype": "Unicommerce Connector Settings",
    "test_method": "alaiy_os_connector_unicommerce.api.test_connection.test_connection",
    # The registry exposes two sync "slots". Map them to whatever your
    # connector actually does; the labels are what the UI shows.
    "sync_categories_method": "alaiy_os_connector_unicommerce.api.sync.trigger_pull_sync",
    "sync_items_method": "alaiy_os_connector_unicommerce.api.sync.trigger_push_sync",
    "sync_status_method": "alaiy_os_connector_unicommerce.api.sync.get_sync_status",
    "sync_categories_label": "Pull",
    "sync_items_label": "Push",
    "is_enabled": 0,
    "connection_status": "untested",
    "health": [
        _health("orders", "Order pull", "pull", "order_sync_frequency"),
        # Item push, B2B orders and purchase orders/GRN share the order and PO intervals.
        _health("items_push", "Item push", "push", "order_sync_frequency", "push"),
        _health("b2b", "B2B order pull", "b2b", "order_sync_frequency"),
        _health("purchase_orders", "Purchase order sync", "purchase_order", "po_sync_frequency"),
        _health("grn", "GRN sync", "grn", "po_sync_frequency"),
    ],
}
