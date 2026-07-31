# Unicommerce Connector — what it actually does

Plain-English map of every flow, written after installing and running this on a
live tenant. No code, no endpoints.

Unicommerce is the warehouse and order system. Alaiy OS is the books and stock.
This connector moves things between them.

---

## The short version

| | Direction | Automatic? |
|---|---|---|
| Orders | Unicommerce → Alaiy OS | yes, every 30 min |
| Order status changes | Unicommerce → Alaiy OS | yes, hourly |
| Cancellations & returns | Unicommerce → Alaiy OS | yes, hourly |
| Products | Unicommerce → Alaiy OS | on demand |
| Products | Alaiy OS → Unicommerce | only if you switch it on |
| Stock levels | Alaiy OS → Unicommerce | only if you switch it on |
| Invoices & shipping labels | Alaiy OS → Unicommerce | manual button |
| Goods received | Alaiy OS → Unicommerce | when you submit a Stock Entry |
| Delivery notes | Unicommerce → Alaiy OS | yes, every 5 min |

**Nothing writes to Unicommerce unless you turn it on or press a button.** Order
and status import are read-only.

---

## Coming IN from Unicommerce

### Orders
Every 30 minutes it looks for orders changed in the last 24 hours, on the sales
channels you've configured. For each one it creates:

- the **customer** (and their billing and delivery addresses)
- the **sales order**, with line items, prices and taxes
- any **product** on the order that Alaiy OS doesn't have yet

Orders on a channel you haven't configured are ignored.

### Order and parcel status
Hourly, it checks orders and parcels for changes and updates them on your side —
so a parcel marked shipped in the warehouse shows as shipped in Alaiy OS.

### Cancellations and returns
Also hourly. Handles:

- a whole order cancelled
- part of an order cancelled (some items removed)
- a customer return
- an RTO (parcel refused or undelivered, sent back)

Returns produce a credit note.

### Delivery notes
Every 5 minutes, once the warehouse has despatched a parcel, the matching
delivery note is created in Alaiy OS.

### Products
Two ways:

1. **Automatically, one at a time** — an order arrives with a product you don't
   have, so it fetches that one.
2. **Bulk** — pull the entire catalogue in one go. Brings name, price,
   dimensions, weight, colour, size, brand, HSN code, category and image. Can be
   limited to a category, or to items changed recently.

---

## Going OUT to Alaiy OS → Unicommerce

Everything here is **off by default**.

### Products (off by default)
With "Upload new items to Unicommerce" switched on, items you flag are pushed to
Unicommerce on a schedule.

### Stock levels (off by default)
With "Enable Inventory Sync" on, it pushes your stock figures to Unicommerce
every few minutes, per warehouse.

### Invoices and shipping labels (manual only)
Buttons on the Sales Order and Pick List. Pressing one asks Unicommerce to raise
the invoice, allocate a courier and generate the shipping label — then pulls the
invoice and label back into Alaiy OS. Can also record the customer payment.

### Goods received (off by default)
With Auto GRN on, submitting a Stock Entry uploads a goods-received file to
Unicommerce.

### Parcel dimensions
If you change the package type on an order that's already confirmed, the new
dimensions are sent across. **This one has no on/off switch** — editing a
confirmed order sends data.

### Shipping manifest
You build a manifest of parcels for a courier and submit it. That closes the
manifest in Unicommerce and pulls back the PDF.

---

## Before any of it works

Four things, and orders import nothing without them:

1. **Login** — the Unicommerce site address, a user's **email** (not a username),
   their password, and the client ID. There's a Test Connection button.
2. **Sales channels** — one record per channel (Flipkart, Amazon, etc). The
   channel code has to match Unicommerce's exactly. Unicommerce has no way to
   list these, so read them off their panel or from existing orders.
3. **Accounting** — each channel needs accounts for tax (IGST, CGST, SGST, UGST,
   TCS), cash, COD charges, gift wrap and freight. A fresh Alaiy OS site has
   none of the tax ones.
4. **Warehouses** — map each Unicommerce facility to an Alaiy OS warehouse, plus
   one for returns.

---

## What it does NOT do

- **Send orders to Unicommerce.** Orders only travel one way, inwards.
- **List your sales channels.** Unicommerce has no such facility. Manual entry.
- **Two-way stock.** Stock goes out only, never comes in.
- **Show progress properly.** The connector card's counters always read zero;
  the sync log records success or failure but not how much it moved.
- **Let you stop a running sync.** No cancel button once it starts.

---

## Worth knowing

- **A channel with no record is silently skipped.** Orders on it are dropped.
  Nothing appears wrong, you just get no orders — it now writes an error
  explaining this, but nothing on screen tells you.
- **Disabling the connector wipes the saved login.** It re-fetches next time you
  enable it, so this only matters if you're toggling it while testing.
- **The tax accounts are a starting point, not a final answer.** If a fresh site
  needed them created, have finance confirm them before real reporting.
- **"Push" on the connector card sends your items TO Unicommerce.** It is not a
  refresh. Don't press it on a live tenant unless that's what you want.
