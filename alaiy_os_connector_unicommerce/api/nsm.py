# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Receiver for Unicommerce's Notification Service (NSM): Uniware calls us the
moment an order is cancelled, a shipment is dispatched or delivered, or a
return is raised, instead of us finding out on the next poll.

Ref: https://documentation.unicommerce.com/docs/nsm_overview.html

The payload is only a signal. Whatever a notification says, the order is
re-read from Unicommerce through the same status pipeline the scheduled polls
use, so a notification can never write a status of its own, a lost or
repeated one is harmless, and the polls stay as the safety net.

Authentication (per the NSM Authentication page): Uniware first POSTs
username and password (Basic auth) to `/oauth/token` and gets an
`access_token` back, then sends that token in the `Authorization` header of
every event. The username and password are a pair WE agree with Unicommerce,
held in the site config (`unicommerce_nsm_username`, `unicommerce_nsm_password`)
— not any seller's real login. The token is derived from them, so it needs no
storage and changes the moment the password does.

Each event is a separate whitelisted method so Unicommerce can be pointed at its
full URL; see `docs/technical/13-nsm-notifications.md` for the URLs and the optional nginx mapping if
they insist on `{base}/<event>` paths.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import frappe

DIRTY_KEY = "unicommerce_nsm_dirty"
LOCK_KEY = "unicommerce_nsm_lock"
#: The portal's own screens key their cached order pages on this, so a
#: refresh shows up on the next request instead of after a cache TTL.
PORTAL_ORDERS_GENERATION_KEY = "globali:orders:gen"

SUCCESS = {"status": "Success", "message": "Detail is updated successfully"}


def _credentials() -> tuple[str, str] | None:
    username = frappe.conf.get("unicommerce_nsm_username")
    password = frappe.conf.get("unicommerce_nsm_password")
    if not username or not password:
        return None
    return str(username), str(password)


def expected_token(username: str, password: str) -> str:
    """The access token for a credential pair. Deterministic, so no state."""
    return hmac.new(password.encode(), f"nsm:{username}".encode(), hashlib.sha256).hexdigest()


def _reply(body: dict, status_code: int = 200) -> None:
    # Unicommerce expects the status at the top level of the JSON body, not
    # wrapped in Frappe's usual {"message": ...}. Filling the response dict
    # and returning nothing gives exactly that.
    frappe.local.response.update(body)
    frappe.local.response["http_status_code"] = status_code


def _basic_credentials() -> tuple[str, str] | None:
    header = frappe.get_request_header("Authorization") or ""
    if not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
    except Exception:
        return None
    username, _, password = decoded.partition(":")
    return username, password


@frappe.whitelist(allow_guest=True, methods=["POST"])
def oauth_token():
    """Uniware's authentication call: validate the agreed credentials and hand
    back the token it will send with every event."""
    ours = _credentials()
    theirs = _basic_credentials()
    if (
        not ours or not theirs
        or not hmac.compare_digest(theirs[0], ours[0])
        or not hmac.compare_digest(theirs[1], ours[1])
    ):
        return _reply({"status": "INVALID_CREDENTIALS"}, 401)
    return _reply({"status": "SUCCESS", "access_token": expected_token(*ours)})


def _authorised() -> bool:
    ours = _credentials()
    if not ours:
        return False
    sent = (frappe.get_request_header("Authorization") or "").strip()
    return bool(sent) and hmac.compare_digest(sent, expected_token(*ours))


def _receive(kind: str):
    if not _authorised():
        return _reply({"status": "Failed", "message": "Invalid token"}, 401)

    payload = frappe.request.get_json(silent=True) if frappe.request else None
    payload = payload if isinstance(payload, dict) else {}
    code = payload.get("saleOrderCode") or (payload.get("saleOrder") or [{}])[0].get("code")
    frappe.logger("unicommerce_nsm").info(f"{kind} {code or ''}")

    request_refresh()
    return _reply(dict(SUCCESS))


def request_refresh() -> None:
    """Ask for a status refresh now.

    Events can arrive in bursts (a manifest dispatching forty packages), so
    this marks the data dirty and starts at most one job; the job keeps going
    while anything arrived since it last looked, which makes the last event of
    a burst count without running forty refreshes.
    """
    cache = frappe.cache()
    cache.set_value(DIRTY_KEY, "1", expires_in_sec=300)
    if cache.get_value(LOCK_KEY) is not None:
        return
    cache.set_value(LOCK_KEY, "1", expires_in_sec=180)
    try:
        frappe.enqueue(
            "alaiy_os_connector_unicommerce.api.nsm.run_refresh", queue="short", timeout=300,
            enqueue_after_commit=False,
        )
    except Exception:
        cache.delete_value(LOCK_KEY)
        frappe.log_error(title="Unicommerce NSM: refresh could not be queued")


def run_refresh() -> None:
    from alaiy_os_connector_unicommerce.unicommerce.order.status import (
        update_shipping_package_status, update_sales_order_status,
    )

    cache = frappe.cache()
    try:
        for _ in range(3):
            if cache.get_value(DIRTY_KEY) is None:
                break
            cache.delete_value(DIRTY_KEY)
            for step in (update_sales_order_status, update_shipping_package_status):
                try:
                    step(window_minutes=15)
                    frappe.db.commit()
                except Exception:
                    frappe.log_error(title=f"Unicommerce NSM: {step.__name__} failed")
            cache.set_value(PORTAL_ORDERS_GENERATION_KEY, str(frappe.utils.now()))
    finally:
        cache.delete_value(LOCK_KEY)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def cancel_so_item():
    """Order Cancel (`/cancelSOItem`)."""
    return _receive("cancelSOItem")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def dispatched_shipment():
    """Shipment Dispatched (`/dispatchedShipment`)."""
    return _receive("dispatchedShipment")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def delivered():
    """Shipment Delivered (`/delivered`)."""
    return _receive("delivered")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def event():
    """Any other NSM event (shipment created / packed / ready to ship, return
    created / courier allocated / completed): all just mean "something changed
    on an order", so one handler serves them."""
    return _receive("event")
