# Client / transport layer

`unicommerce/client/core.py` — `UnicommerceClient.request(endpoint, method, ...)`:

- Adds the Bearer auth header from the Settings singleton.
- On HTTP 401 (not for file uploads — the body stream is already consumed),
  refreshes the token once and retries.
- Appends response body text onto the exception's `reason` so Unicommerce's
  own error detail lands in the log, not just a bare status code.
- Returns `(data_or_bytes, ok: bool)` — **never raises on a Unicommerce-level
  `successful: false` response**, only on transport/HTTP failure. Always
  check the second element.

## Real endpoints by domain

| Domain | Endpoint |
|---|---|
| Orders | `saleorder/get`, `saleOrder/search` |
| Catalog | `catalog/itemType/get`, `product/itemType/search` (note: different path prefix), `catalog/itemType/createOrEdit` / `.../edit` |
| Inventory | `inventory/inventorySnapshot/get`, `inventory/adjust/bulk` |
| Invoicing | `invoice/createInvoiceBySaleOrderCode`, `oms/shippingPackage/createInvoice`, `.../createInvoiceAndAllocateShippingProvider`, `.../createInvoiceAndGenerateLabel`, `invoice/details/get`, `oms/shipment/show` |
| Manifest | `oms/shippingPackage/edit`, `oms/shippingManifest/createclose`, `oms/shippingManifest/get`, `oms/shippingPackage/search` |
| Purchase | `purchase/purchaseOrder/getPurchaseOrders`, `.../getPurchaseOrderDetails`, `purchase/inflowReceipt/getInflowReceipts`, `.../getInflowReceipt` |
| Import job | `data/import/job/create` (multipart CSV) |
| Auth | `GET https://{site}/oauth/token` (password or refresh_token grant) |
