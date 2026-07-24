frappe.ui.form.on("Template Connector Settings", {
  refresh(frm) {
    frm.page.set_title(__("Template Settings"));

    // Mount the shared Alaiy OS connector status card + password reveal.
    alaiy_os.connector_card.mount(frm, "template");
    alaiy_os.connector_card.setup_password_reveal(
      frm,
      "template_api_token",
      "template",
    );

    // Auto-fill Company with the site default if empty.
    if (!frm.doc.template_company) {
      frappe.db
        .get_single_value("Global Defaults", "default_company")
        .then((company) => {
          if (company) frm.set_value("template_company", company);
        });
    }

    frm.add_custom_button(
      __("Test Connection"),
      () => {
        frappe.call({
          // Go through the registry wrapper (not test_connection directly)
          // so a successful test also flips the "Connector Status" card at
          // the top of this form from "Not configured" to "Connected".
          method: "alaiy_os.api.connectors.test_connector",
          args: { connector_id: "template" },
          callback(r) {
            const res = r.message || {};
            frappe.show_alert(
              {
                message:
                  res.message ||
                  (res.success ? __("Connected") : __("Connection failed")),
                indicator: res.success ? "green" : "red",
              },
              res.success ? 5 : 7,
            );
            frm.reload_doc();
          },
        });
      },
      __("Actions"),
    );

    frm.add_custom_button(
      __("Run Pull Sync"),
      () => {
        frappe.call({
          method: "alaiy_os_connector_template.api.sync.trigger_pull_sync",
          callback: () =>
            frappe.show_alert(
              { message: __("Pull sync queued"), indicator: "blue" },
              5,
            ),
        });
      },
      __("Actions"),
    );

    frm.add_custom_button(
      __("Run Push Sync"),
      () => {
        frappe.call({
          method: "alaiy_os_connector_template.api.sync.trigger_push_sync",
          callback: () =>
            frappe.show_alert(
              { message: __("Push sync queued"), indicator: "blue" },
              5,
            ),
        });
      },
      __("Actions"),
    );
  },
});
