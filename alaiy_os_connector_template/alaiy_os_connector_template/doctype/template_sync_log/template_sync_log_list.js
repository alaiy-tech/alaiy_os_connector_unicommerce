const TEMPLATE_SYNC_TYPE_COLORS = {
	pull: "blue",
	push: "orange",
	webhook: "cyan",
};

const TEMPLATE_TRIGGER_COLORS = {
	scheduled: "purple",
	manual: "pink",
	webhook: "cyan",
};

const TEMPLATE_STATUS_COLORS = {
	queued: "grey",
	running: "blue",
	success: "green",
	failed: "red",
	skipped: "yellow",
};

function alaiy_pill(value, colors) {
	if (!value) return "";
	const color = colors[value] || "darkgrey";
	return `<span class="indicator-pill ${color} filterable" data-filter="=,${value}">
		<span>${frappe.utils.escape_html(value)}</span>
	</span>`;
}

frappe.listview_settings["Template Sync Log"] = {
	get_indicator(doc) {
		return [
			__(doc.status),
			TEMPLATE_STATUS_COLORS[doc.status] || "darkgrey",
			`status,=,${doc.status}`,
		];
	},
	formatters: {
		sync_type: (value) => alaiy_pill(value, TEMPLATE_SYNC_TYPE_COLORS),
		trigger: (value) => alaiy_pill(value, TEMPLATE_TRIGGER_COLORS),
		status: (value) => alaiy_pill(value, TEMPLATE_STATUS_COLORS),
	},
};
