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


def backfill_returns(package_codes):
    """One-off: force the invoice-mirror + return-sync path for specific
    packages, instead of waiting for the next scheduled
    update_sales_order_status/update_shipping_package_status tick.

    Needed because cd966b0's fix only takes effect inside
    _create_sales_invoices/create_rto_return, and neither run() above nor
    the scheduler had touched these specific packages since deploying it.

    Usage:
        bench --site <site> execute \
            alaiy_os_connector_unicommerce.unicommerce.run_globali_sync.backfill_returns \
            --kwargs "{'package_codes': ['GLOB00051', 'GLOB00044', ...]}"
    """
    from alaiy_os_connector_unicommerce.unicommerce.client import UnicommerceClient
    from alaiy_os_connector_unicommerce.unicommerce.client.manifest import search_shipping_packages
    from alaiy_os_connector_unicommerce.unicommerce.client.orders import get_sales_order
    from alaiy_os_connector_unicommerce.unicommerce.constants import (
        FACILITY_CODE_FIELD, ORDER_CODE_FIELD, SHIPPING_PACKAGE_CODE_FIELD,
    )
    from alaiy_os_connector_unicommerce.unicommerce.order.pull import _create_sales_invoices
    from alaiy_os_connector_unicommerce.unicommerce.order.cancellation import create_rto_return

    client = UnicommerceClient()
    all_packages = search_shipping_packages(client, updated_since=60 * 24 * 60, facility_code="globali") or []
    by_code = {p["code"]: p for p in all_packages}

    for code in package_codes:
        package = by_code.get(code)
        if not package:
            print(f"{code}: not found in the last 60 days of packages", flush=True)
            continue

        so_code = package.get("saleOrderCode")
        sales_order = frappe.db.get_value("Sales Order", {ORDER_CODE_FIELD: so_code}, "name")
        if not sales_order:
            print(f"{code}: no local Sales Order for {so_code}", flush=True)
            continue

        so_data = get_sales_order(client, so_code)
        try:
            _create_sales_invoices(so_data, frappe.get_doc("Sales Order", sales_order), client)
        except Exception:
            frappe.log_error(
                title=f"Unicommerce: backfill_returns invoice mirror failed for {code}",
                message=frappe.get_traceback(),
            )

        invoice = frappe.db.get_value("Sales Invoice", {SHIPPING_PACKAGE_CODE_FIELD: package["code"]}, "name")
        print(f"{code}: invoice now = {invoice}", flush=True)

        try:
            create_rto_return(package, client=client)
        except Exception:
            frappe.log_error(
                title=f"Unicommerce: backfill_returns create_rto_return failed for {code}",
                message=frappe.get_traceback(),
            )

    frappe.db.commit()
    print("Credit Notes now:", frappe.db.count("Sales Invoice", {"is_return": 1}), flush=True)
