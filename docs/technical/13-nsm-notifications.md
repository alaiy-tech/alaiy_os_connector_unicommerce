# Unicommerce push notifications (NSM)

Unicommerce's Notification Service Management calls us when an order is
cancelled, a shipment is dispatched or delivered, or a return is raised, so a
status change reaches ERPNext in seconds instead of on the next poll.
Reference: <https://documentation.unicommerce.com/docs/nsm_overview.html>

## How it behaves

- A notification is only a signal. `api/nsm.py` re-reads the order through the
  same status pipeline the scheduled polls use (`update_sales_order_status`,
  `update_shipping_package_status`, 15-minute window). A notification can never
  write a status itself, and a lost or repeated one is harmless.
- Bursts are coalesced: events mark the data dirty and start at most one job.
- After a refresh the site cache key `globali:orders:gen` changes, which the
  portal's order pages key on.
- The polls remain the safety net. They now run every 2 minutes
  (`hooks.py`), down from 5.

## Endpoints (all POST, guest-callable, token-checked)

| Purpose | Method path |
|---|---|
| Authentication | `/api/method/alaiy_os_connector_unicommerce.api.nsm.oauth_token` |
| Order cancel | `/api/method/alaiy_os_connector_unicommerce.api.nsm.cancel_so_item` |
| Shipment dispatched | `/api/method/alaiy_os_connector_unicommerce.api.nsm.dispatched_shipment` |
| Shipment delivered | `/api/method/alaiy_os_connector_unicommerce.api.nsm.delivered` |
| Any other event (shipment created, packed, ready to ship; return created, courier allocated, completed) | `/api/method/alaiy_os_connector_unicommerce.api.nsm.event` |

Responses are the shapes the NSM pages specify: `{"status": "SUCCESS",
"access_token": ...}` for authentication, `{"status": "Success", "message": ...}`
for events, `INVALID_CREDENTIALS` / `Failed` with HTTP 401 otherwise.

## Credentials

Per the NSM Authentication page, Uniware POSTs a username and password (Basic
auth) to the authentication URL and receives a token, which it then sends in the
`Authorization` header of every event. The pair is one we agree with Unicommerce
and keep in the site config; it is not any seller's login. The token is derived
from it (HMAC), so nothing is stored and changing the password invalidates it.

Set on the server, generating the password there so it is never typed into chat:

```bash
bench --site <site> set-config unicommerce_nsm_username "<agreed-username>"
bench --site <site> set-config unicommerce_nsm_password "$(openssl rand -hex 24)"
bench --site <site> get-config unicommerce_nsm_password   # read it once to hand to Unicommerce
```

## If Unicommerce can only call `{base}/<event>` paths

The NSM pages show events at `https://{PartnerBaseUrl}/delivered`,
`/cancelSOItem`, `/dispatchedShipment` and `/oauth/token`. Ask them to
configure each event's full URL from the table above. If they cannot, map those
paths onto the methods with a rewrite in the site's nginx server block:

```nginx
location = /unicommerce-nsm/oauth/token        { rewrite ^ /api/method/alaiy_os_connector_unicommerce.api.nsm.oauth_token break; proxy_pass http://frappe-bench-frappe; }
location = /unicommerce-nsm/cancelSOItem       { rewrite ^ /api/method/alaiy_os_connector_unicommerce.api.nsm.cancel_so_item break; proxy_pass http://frappe-bench-frappe; }
location = /unicommerce-nsm/dispatchedShipment { rewrite ^ /api/method/alaiy_os_connector_unicommerce.api.nsm.dispatched_shipment break; proxy_pass http://frappe-bench-frappe; }
location = /unicommerce-nsm/delivered          { rewrite ^ /api/method/alaiy_os_connector_unicommerce.api.nsm.delivered break; proxy_pass http://frappe-bench-frappe; }
```

with `PartnerBaseUrl` = `<site-domain>/unicommerce-nsm`. Match the upstream name
and any proxy headers to the existing locations in that file.

## Checking it

```bash
# authentication (expect {"status": "SUCCESS", "access_token": ...})
curl -s -X POST -u "<username>:<password>" https://<site-domain>/api/method/alaiy_os_connector_unicommerce.api.nsm.oauth_token
# an event with the token (expect {"status": "Success", ...}); a wrong token gives 401
curl -s -X POST -H "Authorization: <token>" -H "Content-Type: application/json" \
  -d '{"saleOrderCode": "TEST"}' https://<site-domain>/api/method/alaiy_os_connector_unicommerce.api.nsm.event
```

Then change an order's status in Unicommerce and watch it appear in ERPNext
within a minute.
