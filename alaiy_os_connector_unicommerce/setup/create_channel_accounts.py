"""
Create the GL accounts a Unicommerce Channel record requires, for a company
that doesn't have them yet.

A Unicommerce Channel mandates eight accounts (igst / cgst / sgst / ugst /
tcs / fnf / cod / gift_wrap) before it can be saved. A stock ERPNext chart
for an Indian company ships none of the GST ones -- in ERPNext v15+ those
come from the separate india_compliance app, driven by the real GSTIN.

So these are PLACEHOLDERS to unblock connector setup and testing, not a
substitute for proper GST configuration. Two consequences worth knowing:

  * If india_compliance is installed later it will create its own GST
    accounts, and anything already posted against these will have to be
    migrated. Safe only while the books are empty.
  * Freight charged TO a customer is income. ERPNext's default
    "Freight and Forwarding Charges" is an EXPENSE account, so this creates
    an income account for the collected side rather than reusing it -- the
    one mapping most likely to be wrong if taken from the default chart.

Idempotent: an existing account is reused, never modified.

Run:
    bench --site <site> execute alaiy_os_connector_unicommerce.setup.create_channel_accounts.run --kwargs "{'company': 'Alaiy'}"

Report what it would do without writing:
    ... --kwargs "{'company': 'Alaiy', 'dry_run': True}"
"""

import frappe

# (account_name, root group to hang it under, account_type)
_TAX_ACCOUNTS = [
    ("Output Tax IGST", "Duties and Taxes", "Tax"),
    ("Output Tax CGST", "Duties and Taxes", "Tax"),
    ("Output Tax SGST", "Duties and Taxes", "Tax"),
    ("Output Tax UGST", "Duties and Taxes", "Tax"),
    ("TCS Payable", "Duties and Taxes", "Tax"),
]

# Charges collected FROM the customer are income, not expense.
_INCOME_ACCOUNTS = [
    ("COD Charges Collected", "Income"),
    ("Gift Wrap Charges Collected", "Income"),
    ("Freight Charges Collected", "Income"),
]


def _abbr(company):
    return frappe.get_cached_value("Company", company, "abbr")


def _find_group(company, name_fragment, root_type):
    """A group account to parent new accounts under, matched by name then by
    root_type so this works on a chart that names things differently."""
    abbr = _abbr(company)
    exact = f"{name_fragment} - {abbr}"
    if frappe.db.exists("Account", exact):
        return exact
    rows = frappe.get_all("Account", filters={
        "company": company, "is_group": 1, "root_type": root_type,
        "account_name": ["like", f"%{name_fragment}%"]}, pluck="name")
    if rows:
        return rows[0]
    # Fall back to the root of that type -- better than failing outright.
    rows = frappe.get_all("Account", filters={
        "company": company, "is_group": 1, "root_type": root_type,
        "parent_account": ["in", ["", None]]}, pluck="name")
    return rows[0] if rows else None


def _ensure_account(company, account_name, parent, root_type, account_type, dry_run):
    abbr = _abbr(company)
    name = f"{account_name} - {abbr}"
    if frappe.db.exists("Account", name):
        return name, "exists"
    if dry_run:
        return name, "would create"
    doc = frappe.new_doc("Account")
    doc.account_name = account_name
    doc.company = company
    doc.parent_account = parent
    doc.root_type = root_type
    doc.report_type = "Balance Sheet" if root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
    if account_type:
        doc.account_type = account_type
    doc.is_group = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name, "created"


def run(company=None, dry_run=False):
    company = company or frappe.defaults.get_global_default("company")
    if not company:
        frappe.throw("company is required")

    posted = frappe.db.count("GL Entry", {"company": company})
    print(f"[create_channel_accounts] company={company} abbr={_abbr(company)}")
    print(f"  existing GL entries: {posted}")
    if posted:
        print("  NOTE: this company already has postings. These placeholder accounts are")
        print("  only safe to introduce on empty books -- migrating away from them later")
        print("  means reposting anything booked against them. Check with finance first.")

    tax_parent = _find_group(company, "Duties and Taxes", "Liability")
    income_parent = _find_group(company, "Income", "Income")
    print(f"  tax accounts under   : {tax_parent}")
    print(f"  income accounts under: {income_parent}")
    if not tax_parent or not income_parent:
        frappe.throw("Could not resolve parent groups for the new accounts")

    results = []
    for account_name, _frag, account_type in _TAX_ACCOUNTS:
        results.append(_ensure_account(
            company, account_name, tax_parent, "Liability", account_type, dry_run))
    for account_name, root_type in _INCOME_ACCOUNTS:
        results.append(_ensure_account(
            company, account_name, income_parent, root_type, None, dry_run))

    if not dry_run:
        frappe.db.commit()

    print()
    for name, state in results:
        print(f"  {state:14} {name}")

    created = sum(1 for _, s in results if s == "created")
    print(f"\n[create_channel_accounts] {created} created, "
          f"{sum(1 for _, s in results if s == 'exists')} already existed")
    if dry_run:
        print("  DRY RUN -- nothing written.")
        return

    print("\n  Channel field -> account:")
    abbr = _abbr(company)
    print(f"    igst_account          : Output Tax IGST - {abbr}")
    print(f"    cgst_account          : Output Tax CGST - {abbr}")
    print(f"    sgst_account          : Output Tax SGST - {abbr}")
    print(f"    ugst_account          : Output Tax UGST - {abbr}")
    print(f"    tcs_account           : TCS Payable - {abbr}")
    print(f"    cod_account           : COD Charges Collected - {abbr}")
    print(f"    gift_wrap_account     : Gift Wrap Charges Collected - {abbr}")
    print(f"    fnf_account           : Freight Charges Collected - {abbr}")
    print("\n  These are placeholders. Have finance confirm them, and prefer")
    print("  india_compliance's own GST accounts before real GST reporting.")
