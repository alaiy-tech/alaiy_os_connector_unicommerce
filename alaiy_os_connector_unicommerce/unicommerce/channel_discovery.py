# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Discover Unicommerce channels we have no local record for.

Order pull only imports orders whose channel has an enabled Unicommerce
Channel record. Nothing creates those records -- they are made by hand, and
`channel_id` has to match Unicommerce's own channel code exactly.

That combination fails silently. An order on a channel nobody added locally
is fetched from Unicommerce, dropped by the filter, and never mentioned
again: no log, no counter, no error. The existing guard in pull.py only
fires when the local list is *entirely* empty, so a site with 44 channels
configured and a 45th live in Unicommerce looks completely healthy.

On Globali that hid four channels -- MYNTRAPPMP, NYKAA_FASHION,
TATACLIQ_GLOBALI and SHOPIFY_ALTOMODA -- and 1,255 orders, 1,038 of them
COMPLETE, for months. Adding those four by hand fixes today and leaves the
next marketplace to fail the same way.

So a channel seen on a real order but missing locally gets a record created
automatically, ALWAYS DISABLED. Disabled means the pull filter still skips
it, so this imports nothing on its own and cannot start writing invoices or
stock against a channel nobody has reviewed. What it does is make the
channel visible in the UI, with its accounts already filled in, so enabling
it is a decision someone takes deliberately rather than a gap nobody can
see.
"""

import frappe

from alaiy_os_connector_unicommerce.unicommerce.constants import SETTINGS_DOCTYPE

CHANNEL_DOCTYPE = "Unicommerce Channel"


def get_configured_channels() -> set[str]:
    """Channel codes with an ENABLED local record -- the set order pull imports."""
    return set(
        frappe.get_all(CHANNEL_DOCTYPE, filters={"enabled": 1}, pluck="channel_id", limit=0)
    )


def get_known_channels() -> set[str]:
    """Every local channel code, enabled or not.

    Discovery keys off this rather than the enabled set: a channel that was
    discovered earlier and deliberately left disabled must not be recreated
    (it already exists), nor reported as new on every run.
    """
    return set(frappe.get_all(CHANNEL_DOCTYPE, pluck="channel_id", limit=0))


def _default_warehouse(company: str) -> str | None:
    """Warehouse for a discovered channel.

    `warehouse` is the one mandatory field on Unicommerce Channel with no
    autofill in the doctype's own validate(). Copy it from an existing
    channel on the same company -- on a site already running, that is the
    warehouse every other channel uses, which is the only defensible guess.
    Falls back to the company default.

    Returns None if neither exists, which leaves the record uncreatable --
    reported as a skip rather than guessed at.
    """
    existing = frappe.get_all(
        CHANNEL_DOCTYPE,
        filters={"company": company},
        pluck="warehouse",
        order_by="modified desc",
        limit=1,
    )
    if existing and existing[0]:
        return existing[0]

    return frappe.get_cached_value("Company", company, "default_warehouse") or None


def create_disabled_channel(channel_id: str, settings=None) -> str | None:
    """Create a disabled Unicommerce Channel for `channel_id`.

    Returns the new record's name, or None if it could not be created.
    Never raises: discovery runs inside the order sync, and a channel that
    cannot be auto-created must not take the whole sync down with it.

    The 8 GL accounts, cost centre and cash account are filled by the
    doctype's own _autofill_accounts() on validate, so they are not set
    here -- keeping one source of truth for what a placeholder account is
    called.
    """
    if settings is None:
        settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)

    company = settings.unicommerce_company
    if not company:
        return None

    warehouse = _default_warehouse(company)
    if not warehouse:
        return None

    try:
        doc = frappe.new_doc(CHANNEL_DOCTYPE)
        doc.channel_id = channel_id
        # Display name is editable afterwards; the code is the only thing
        # known at discovery time and matching it keeps the two obviously
        # the same channel.
        doc.display_name = channel_id
        doc.company = company
        doc.warehouse = warehouse
        doc.enabled = 0
        if settings.default_customer_group:
            doc.customer_group = settings.default_customer_group
        doc.insert(ignore_permissions=True)
        return doc.name
    except Exception:
        frappe.log_error(
            title=f"Unicommerce: could not auto-create channel {channel_id}",
            message=frappe.get_traceback(),
        )
        return None


def discover_channels(channel_ids, settings=None) -> dict:
    """Create disabled records for any code in `channel_ids` we don't hold.

    `channel_ids` is whatever was seen on real orders this run. Returns a
    summary dict for the caller to log.
    """
    known = get_known_channels()
    unknown = {c for c in channel_ids if c and c not in known}

    summary = {"discovered": [], "failed": []}
    if not unknown:
        return summary

    if settings is None:
        settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)

    for channel_id in sorted(unknown):
        if create_disabled_channel(channel_id, settings=settings):
            summary["discovered"].append(channel_id)
        else:
            summary["failed"].append(channel_id)

    if summary["discovered"] or summary["failed"]:
        frappe.log_error(
            title="Unicommerce: new channels found in Unicommerce",
            message=(
                "Orders arrived on channels with no local Unicommerce Channel record.\n\n"
                f"Created (DISABLED, importing nothing until enabled): "
                f"{', '.join(summary['discovered']) or 'none'}\n"
                f"Could not create: {', '.join(summary['failed']) or 'none'}\n\n"
                "Review each one and enable it to start importing its orders. "
                "Enabling imports that channel's order history, which creates "
                "Sales Orders, Invoices and stock movements."
            ),
        )

    return summary


def report_skipped(skipped: dict) -> None:
    """Log channels whose orders were dropped this run.

    Separate from discovery: a channel can exist locally and be deliberately
    disabled, in which case nothing is created but the orders are still being
    skipped and that should be visible rather than silent.
    """
    if not skipped:
        return

    lines = "\n".join(f"  {code}: {count} order(s)" for code, count in sorted(skipped.items()))
    frappe.log_error(
        title="Unicommerce: orders skipped, channel not enabled",
        message=(
            "These orders were fetched from Unicommerce and NOT imported, because "
            "their channel has no enabled Unicommerce Channel record:\n\n"
            f"{lines}\n\n"
            "Enable the channel to import them."
        ),
    )
