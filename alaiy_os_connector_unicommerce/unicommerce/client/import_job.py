# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Bulk CSV import job endpoint. Ref: https://documentation.unicommerce.com/"""

import frappe
from frappe import _


def create_import_job(client, job_name: str, csv_filename: str, facility_code: str, job_type: str = "CREATE_NEW"):
    """
    Create an import job by specifying the job name and a CSV file.

    job_name: import job code string specified by Unicommerce
    csv_filename: name of the CSV file (already uploaded as a Frappe File)
    facility_code: facility where the import should happen
    job_type: create / update code
    """
    file_obj = _safe_open_csv(csv_filename)
    try:
        response, _status = client.request(
            endpoint="/services/rest/v1/data/import/job/create",
            params={"name": job_name, "importOption": job_type},
            files=[("file", (csv_filename, file_obj, "text/csv"))],
            headers={"Facility": facility_code, "cache-control": "no-cache"},
        )
        return response
    finally:
        file_obj.close()


def _safe_open_csv(csv_name: str):
    from frappe.utils.file_manager import get_file_path

    if csv_name.split(".")[-1].lower().strip() != "csv":
        frappe.throw(_("Only CSV files can be uploaded."))
    return open(get_file_path(csv_name), "rb")
