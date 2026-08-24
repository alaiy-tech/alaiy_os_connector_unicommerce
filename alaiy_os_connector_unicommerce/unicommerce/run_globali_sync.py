"""
One-off: pull real inventory from Unicommerce, then create Delivery Notes for
dispatched packages -- in that order, since delivery note creation needs
accurate Bin data to avoid NegativeStockError.

Run via bench execute (reliable for a real function call; piping multi-line
blocks into `bench console` over stdin does not reliably execute as one
block):

    bench --site <site> execute \
        alaiy_os_connector_unicommerce.unicommerce.run_globali_sync.run
"""

import frappe


def run():
    from alaiy_os_connector_unicommerce.unicommerce.inventory.pull import pull_inventory_from_unicommerce

    from alaiy_os_connector_unicommerce.unicommerce.constants import SETTINGS_DOCTYPE
    print("unicommerce_company setting:", frappe.db.get_single_value(SETTINGS_DOCTYPE, "unicommerce_company"), flush=True)

    print("=== inventory pull ===", flush=True)
    result = pull_inventory_from_unicommerce(force=True)
    print("result:", result, flush=True)
    print("Bin rows with stock:", frappe.db.count("Bin", {"actual_qty": [">", 0]}), flush=True)

    unsuccessful = frappe.get_all(
        "Error Log", filters={"method": ["like", "%inventory pull: unsuccessful response%"]},
        fields=["name", "method", "creation"], order_by="creation desc", limit=5,
    )
    print("unsuccessful-response errors:", len(unsuccessful), flush=True)
    for e in unsuccessful:
        print(" -", e.method, flush=True)

    pull_failed = frappe.get_all(
        "Error Log", filters={"method": ["like", "%inventory pull failed for%"]},
        fields=["name", "method", "error", "creation"], order_by="creation desc", limit=3,
    )
    print("pull-failed-for-warehouse errors:", len(pull_failed), flush=True)
    for e in pull_failed:
        print(" -", e.method, flush=True)
        print("   ", (e.error or "")[-800:], flush=True)

    from alaiy_os_connector_unicommerce.unicommerce.fulfillment.delivery_note import prepare_delivery_note

    print("=== delivery notes ===", flush=True)
    prepare_delivery_note()
    print("Delivery Notes:", frappe.db.count("Delivery Note"), flush=True)

    print("DONE", flush=True)


def backfill_returns(days=90):
    """One-off: force the invoice-mirror + return-sync path for EVERY
    RETURNED/RETURN_EXPECTED package in the lookback window, instead of
    waiting for the next scheduled update_sales_order_status/
    update_shipping_package_status tick.

    Needed because cd966b0's fix only takes effect inside
    _create_sales_invoices/create_rto_return, and neither run() above nor
    the scheduler had touched any of these packages since deploying it.
    Discovers the real list from Unicommerce itself rather than a
    hardcoded set -- the 9 packages found earlier via Error Log were only
    the ones that happened to hit that specific error message; there is no
    reason to assume they're the only returns affected.

    Usage:
        bench --site <site> execute \
            alaiy_os_connector_unicommerce.unicommerce.run_globali_sync.backfill_returns
        # or with a wider/narrower window:
        bench --site <site> execute \
            alaiy_os_connector_unicommerce.unicommerce.run_globali_sync.backfill_returns \
            --kwargs "{'days': 180}"
    """
    from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
    from alaiy_os_connector_unicommerce.unicommerce.client.manifest import search_shipping_packages
    from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
    from alaiy_os_connector_unicommerce.unicommerce.constants import (
        FACILITY_CODE_FIELD, ORDER_CODE_FIELD, SHIPPING_PACKAGE_CODE_FIELD,
    )
    from alaiy_os_connector_unicommerce.unicommerce.order.pull import _create_sales_invoices
    from alaiy_os_connector_unicommerce.unicommerce.order.cancellation import create_rto_return
    from alaiy_os_connector_unicommerce.unicommerce.order.status import SHIPMENT_RETURN_STATES

    client = UnicommerceClient()
    all_packages = search_shipping_packages(client, updated_since=days * 24 * 60, facility_code="globali") or []
    returned_packages = [p for p in all_packages if p.get("status") in SHIPMENT_RETURN_STATES]
    print(f"{len(all_packages)} packages scanned, {len(returned_packages)} in a return state", flush=True)

    def safe_log(title, message):
        # frappe.log_error can itself fail (confirmed live: a broken
        # `webhooks` global on this site threw AttributeError from inside
        # log_error's own after_insert hook, escaping the caller's except
        # block entirely and killing this whole loop at GLOB00367). A
        # logging call must never be able to take down the batch it's
        # trying to report on -- fall back to plain print if it does.
        try:
            frappe.log_error(title=title, message=message)
        except Exception:
            print(f"[log_error itself failed] {title}\n{message[-500:]}", flush=True)

    for package in returned_packages:
        code = package["code"]
        so_code = package.get("saleOrderCode")
        sales_order = frappe.db.get_value("Sales Order", {ORDER_CODE_FIELD: so_code}, "name")
        if not sales_order:
            print(f"{code}: no local Sales Order for {so_code}", flush=True)
            continue

        so_data = get_sales_order(client, so_code)
        try:
            _create_sales_invoices(so_data, frappe.get_doc("Sales Order", sales_order), client)
        except Exception:
            frappe.db.rollback()
            safe_log(f"Unicommerce: backfill_returns invoice mirror failed for {code}", frappe.get_traceback())

        invoice = frappe.db.get_value("Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: package["code"]}, "name")
        print(f"{code}: invoice now = {invoice}", flush=True)

        try:
            create_rto_return(package, client=client)
        except Exception:
            frappe.db.rollback()
            safe_log(f"Unicommerce: backfill_returns create_rto_return failed for {code}", frappe.get_traceback())

    frappe.db.commit()
    print("Credit Notes now:", frappe.db.count("Sales Invoice", {"is_return": 1}), flush=True)
