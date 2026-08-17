# Unicommerce Connector — Features

Connects Unicommerce (warehouse and order management) with Alaiy OS (accounting
and stock).

---

## Order Management

**Order import** — Pulls orders from Unicommerce every 30 minutes. Creates the
customer, their billing and delivery addresses, and the sales order with all
line items, prices and taxes.

**Order status sync** — Keeps order status in step with the warehouse, hourly.

**Parcel status sync** — Tracks each parcel's progress and updates it in
Alaiy OS, hourly.

**Order cancellation** — Full order cancellations flow through automatically.

**Partial cancellation** — Handles orders where only some items are cancelled,
adjusting quantities accordingly.

**Customer returns** — Imports returns and raises the credit note.

**RTO handling** — Processes refused and undelivered parcels sent back by the
courier.

**Multi-channel** — Runs across as many sales channels as you configure —
Flipkart, Amazon and others — each with its own warehouse and accounting setup.

---

## Product Management

**Catalogue import** — Pulls the entire Unicommerce catalogue into Alaiy OS:
name, price, dimensions, weight, colour, size, brand, HSN code, category and
image.

**Filtered import** — Import a single category, or only items changed recently.

**Automatic product creation** — Any product on an incoming order that Alaiy OS
doesn't have is created automatically.

**Product upload** — Push Alaiy OS items to Unicommerce on a schedule.

---

## Inventory

**Stock sync** — Pulls Unicommerce's real per-facility stock into Alaiy OS
every 5 minutes, as an audited Stock Reconciliation per warehouse. Alaiy OS
was previously the source of truth pushing stock out; that direction has
been removed — Unicommerce is now the source of truth for physical stock.

**Warehouse mapping** — Map each Unicommerce facility to an Alaiy OS warehouse,
with a separate returns warehouse.

---

## Fulfilment

**Invoice generation** — Raise the invoice in Unicommerce directly from the Sales
Order or Pick List, and pull it back into Alaiy OS.

**Courier allocation** — Assign a shipping provider as part of invoicing.

**Shipping labels** — Generate and retrieve the label PDF.

**Delivery notes** — Created automatically every 5 minutes as the warehouse
despatches.

**Pick lists** — Pick list support with order-level detail tracking.

**Shipping manifests** — Build a manifest of parcels, submit it to close in
Unicommerce, and get the PDF back.

**Parcel dimensions** — Set a package type on an order and the dimensions are
sent to Unicommerce.

**Payment entries** — Record customer payment against the invoice automatically.

---

## Purchasing

**Purchase Order import** — Pulls Purchase Orders from Unicommerce into Alaiy
OS's own Purchase Order doctype, when enabled.

**GRN import** — Pulls goods-received receipts (GRNs) against a Purchase
Order from Unicommerce into Alaiy OS Purchase Receipts, when enabled.

**Goods received notes (outbound)** — Submit a Stock Entry in Alaiy OS and it
uploads as a GRN to Unicommerce (a separate, independent flow from GRN
import above).

---

## Setup & Operations

**Connection test** — One-click check that credentials and connectivity are
working.

**Automatic token management** — Handles authentication and refresh in the
background.

**Sync log** — Every sync run recorded with status, timing and errors.

**Configurable schedules** — Set how often orders and inventory sync.

**Per-channel accounting** — Separate tax, COD, gift wrap, freight and cash
accounts per sales channel.

**Tax handling** — IGST, CGST, SGST, UGST and TCS supported.

**Custom fields** — Unicommerce order codes, facility codes and channel IDs
stored on your documents for traceability.
