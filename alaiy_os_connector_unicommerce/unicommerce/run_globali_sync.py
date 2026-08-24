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

    from alaiy_os_connector_unicommerce.unicommerce.fulfillment.delivery_note import prepare_delivery_note

    print("=== delivery notes ===", flush=True)
    prepare_delivery_note()
    print("Delivery Notes:", frappe.db.count("Delivery Note"), flush=True)

    print("DONE", flush=True)
