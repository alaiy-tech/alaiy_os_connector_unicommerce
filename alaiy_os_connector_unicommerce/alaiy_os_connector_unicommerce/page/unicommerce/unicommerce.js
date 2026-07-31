frappe.pages["unicommerce"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Unicommerce",
		single_column: true,
	});

	page.set_secondary_action("Settings", function () {
		frappe.set_route("Form", "Unicommerce Connector Settings");
	}, "settings");

	$(page.body).html(`
		<div class="uc-page">
			<div class="container uc-container">

				<!-- Connection -->
				<div class="uc-card">
					<div class="uc-card-body">
						<div id="uc-connector-status"></div>
						<button id="uc-test-btn" class="uc-btn uc-btn-secondary">
							<i class="fa fa-plug"></i> Test Connection
						</button>
					</div>
				</div>

				<!-- Stats -->
				<div class="uc-card">
					<div class="uc-card-header">
						<span class="uc-icon-badge"><i class="fa fa-bar-chart"></i></span>
						<div class="uc-card-header-text">
							<h5>Overview</h5>
							<p>Local catalogue and sync state, plus live tenant counts.</p>
						</div>
					</div>
					<div class="uc-card-body">
						<div id="uc-stats-grid"></div>
					</div>
				</div>

				<!-- Orders -->
				<div class="uc-card">
					<div class="uc-card-header">
						<span class="uc-icon-badge"><i class="fa fa-shopping-cart"></i></span>
						<div class="uc-card-header-text">
							<h5>Orders</h5>
							<p>Pull orders, status changes, cancellations and returns from Unicommerce.</p>
						</div>
					</div>
					<div class="uc-card-body">
						<div class="uc-info-strip">
							<span class="uc-pill"><i class="fa fa-check-circle"></i> Sales Orders</span>
							<span class="uc-pill"><i class="fa fa-refresh"></i> Status &amp; parcels</span>
							<span class="uc-pill"><i class="fa fa-undo"></i> Cancellations &amp; returns</span>
							<span class="uc-pill uc-pill-muted"><i class="fa fa-clock-o"></i> Also runs every 30 min</span>
						</div>
						<p class="uc-muted">Only orders on an enabled Unicommerce Channel are imported. Orders on an
							unmapped channel are silently skipped.</p>
						<button id="uc-pull-btn" class="uc-btn uc-btn-primary">
							<i class="fa fa-cloud-download"></i> Pull Orders Now
						</button>
						<div id="uc-pull-log" class="uc-log"></div>
					</div>
				</div>

				<!-- Products -->
				<div class="uc-card">
					<div class="uc-card-header">
						<span class="uc-icon-badge"><i class="fa fa-cubes"></i></span>
						<div class="uc-card-header-text">
							<h5>Products</h5>
							<p>Import the Unicommerce catalogue, or push local items out to it.</p>
						</div>
					</div>
					<div class="uc-card-body">
						<div class="uc-info-strip">
							<span class="uc-pill"><i class="fa fa-tag"></i> Name, price, HSN</span>
							<span class="uc-pill"><i class="fa fa-arrows-alt"></i> Dimensions &amp; weight</span>
							<span class="uc-pill"><i class="fa fa-sitemap"></i> Category</span>
						</div>
						<p class="uc-muted">Import is read-only and safe to re-run &mdash; items already linked are skipped.</p>
						<button id="uc-catalogue-btn" class="uc-btn uc-btn-primary">
							<i class="fa fa-cloud-download"></i> Import Catalogue
						</button>
						<button id="uc-push-items-btn" class="uc-btn uc-btn-warning">
							<i class="fa fa-cloud-upload"></i> Push Items to Unicommerce
						</button>
						<div id="uc-products-log" class="uc-log"></div>
					</div>
				</div>

				<!-- Categories -->
				<div class="uc-card">
					<div class="uc-card-header">
						<span class="uc-icon-badge"><i class="fa fa-sitemap"></i></span>
						<div class="uc-card-header-text">
							<h5>Categories</h5>
							<p>Create one Item Group per Unicommerce category so imported items land correctly.</p>
						</div>
					</div>
					<div class="uc-card-body">
						<p class="uc-muted">Unicommerce has no endpoint that lists categories, so this walks the
							catalogue to find them. Run it before a large product import.</p>
						<button id="uc-categories-btn" class="uc-btn uc-btn-primary">
							<i class="fa fa-refresh"></i> Sync Item Groups
						</button>
						<button id="uc-view-groups-btn" class="uc-btn uc-btn-secondary">
							<i class="fa fa-list"></i> View Item Groups
						</button>
						<div id="uc-categories-log" class="uc-log"></div>
					</div>
				</div>

				<!-- Setup -->
				<div class="uc-card">
					<div class="uc-card-header">
						<span class="uc-icon-badge"><i class="fa fa-cogs"></i></span>
						<div class="uc-card-header-text">
							<h5>Setup</h5>
							<p>Channels, warehouse mapping and fulfilment records.</p>
						</div>
					</div>
					<div class="uc-card-body">
						<p class="uc-muted">Channel codes must match Unicommerce exactly. There is no endpoint to list
							them, so they are entered by hand.</p>
						<div class="uc-btn-row">
							<button class="uc-btn uc-btn-secondary" data-route-list="Unicommerce Channel">
								<i class="fa fa-random"></i> Channels
							</button>
							<!-- Warehouse mapping is a child table on the settings Single, so it
							     has no list view of its own -- route to the form instead. -->
							<button id="uc-warehouses-btn" class="uc-btn uc-btn-secondary">
								<i class="fa fa-building"></i> Warehouse Mapping
							</button>
							<button class="uc-btn uc-btn-secondary" data-route-list="Unicommerce Shipment Manifest">
								<i class="fa fa-truck"></i> Shipment Manifests
							</button>
							<button class="uc-btn uc-btn-secondary" data-route-list="Unicommerce Package Type">
								<i class="fa fa-archive"></i> Package Types
							</button>
						</div>
					</div>
				</div>

				<!-- Logs -->
				<div class="uc-card">
					<div class="uc-card-header">
						<span class="uc-icon-badge"><i class="fa fa-history"></i></span>
						<div class="uc-card-header-text">
							<h5>Recent Syncs</h5>
							<p>Last ten runs.</p>
						</div>
					</div>
					<div class="uc-card-body">
						<div id="uc-logs"></div>
						<button class="uc-btn uc-btn-secondary" data-route-list="Unicommerce Sync Log">
							<i class="fa fa-list"></i> All Sync Logs
						</button>
					</div>
				</div>

			</div>
		</div>
	`);

	// ---------------------------------------------------------------- helpers

	function busy(btn, label) {
		btn.disabled = true;
		btn.dataset.label = btn.innerHTML;
		btn.innerHTML = '<span class="uc-spinner"></span> ' + label;
	}

	function idle(btn) {
		btn.disabled = false;
		if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
	}

	function say(container_id, message, kind) {
		var el = document.getElementById(container_id);
		if (!el) return;
		el.className = "uc-log uc-log-" + (kind || "info");
		el.textContent = message;
	}

	/* Every trigger enqueues onto the long queue and returns immediately -- the
	   sync layer does not write progress counters yet, so there is nothing to
	   poll. Reporting "queued" and refreshing the log table is honest; a
	   progress bar here would be fabricated. */
	function enqueue(method, btn_id, log_id, busy_label, args) {
		var btn = document.getElementById(btn_id);
		busy(btn, busy_label);
		frappe.call({
			method: method,
			args: args || {},
			callback: function (r) {
				idle(btn);
				var m = r.message || {};
				say(log_id, m.message || "Queued. It appears in Recent Syncs below once the worker picks it up.", "ok");
				/* The log row is created by the enqueued job, not by this call, so
				   a single quick refresh lands before the row is committed and shows
				   nothing. Poll a few times instead, spread far enough apart to catch
				   both a fast no-op sync and a slower real one. */
				[1500, 5000, 15000, 45000].forEach(function (delay) {
					setTimeout(load_logs, delay);
				});
				setTimeout(load_stats, 5000);
			},
			error: function () {
				idle(btn);
				say(log_id, "Failed to queue. See the Error Log.", "error");
			},
		});
	}

	// ------------------------------------------------------------ connection

	function render_connector_status() {
		frappe.call({
			method: "alaiy_os.api.connectors.get_all_connectors",
			callback: function (r) {
				var connector = (r.message || []).find(function (c) {
					return c.connector_id === "unicommerce";
				});
				if (!connector) return;
				document.getElementById("uc-connector-status").innerHTML =
					alaiy_os.connector_card._html(connector);
			},
		});
	}

	function test_connection() {
		var btn = document.getElementById("uc-test-btn");
		busy(btn, "Testing");
		frappe.call({
			method: "alaiy_os_connector_unicommerce.api.test_connection.test_connection",
			callback: function () { idle(btn); render_connector_status(); },
			error: function () { idle(btn); render_connector_status(); },
		});
	}

	// ----------------------------------------------------------------- stats

	function stat_group(title, cards, accent) {
		var html = '<div class="uc-stat-group-title">' + title + '</div><div class="uc-stats-grid">';
		cards.forEach(function (c) {
			html += '<div class="uc-stat-tile uc-stat-' + accent + '">' +
				'<div class="uc-stat-value">' + c.value + "</div>" +
				'<div class="uc-stat-label">' + c.label + "</div>" +
				"</div>";
		});
		return html + "</div>";
	}

	function skeleton_group(title, count) {
		var html = '<div class="uc-stat-group-title">' + title + '</div><div class="uc-stats-grid">';
		for (var i = 0; i < count; i++) {
			html += '<div class="uc-stat-tile uc-stat-skeleton">' +
				'<div class="uc-skeleton uc-skeleton-value"></div>' +
				'<div class="uc-skeleton uc-skeleton-label"></div>' +
				"</div>";
		}
		return html + "</div>";
	}

	function load_stats() {
		var grid = document.getElementById("uc-stats-grid");
		grid.innerHTML = skeleton_group("Alaiy OS (local)", 8);

		frappe.call({
			method: "alaiy_os_connector_unicommerce.api.dashboard.get_dashboard_stats",
			callback: function (r) {
				var s = r.message;
				if (!s) return;
				grid.innerHTML = stat_group("Alaiy OS (local)", [
					{ label: "Items (all)", value: s.items_total },
					{ label: "Items from Unicommerce", value: s.items_from_unicommerce },
					{ label: "Items flagged for push", value: s.items_flagged_for_push },
					{ label: "Categories mapped", value: s.item_groups_mapped },
					{ label: "Orders synced", value: s.orders_synced },
					{ label: "Invoices synced", value: s.invoices_synced },
					{ label: "Channels (enabled / total)", value: s.channels_enabled + " / " + s.channels_total },
					{ label: "Warehouse mappings", value: s.warehouse_mappings },
				], "local") + '<div id="uc-side-stats">' + skeleton_group("Unicommerce (live)", 2) + "</div>";

				frappe.call({
					method: "alaiy_os_connector_unicommerce.api.dashboard.get_unicommerce_side_stats",
					callback: function (r2) {
						var target = document.getElementById("uc-side-stats");
						if (!r2.message || !target) return;
						target.innerHTML = stat_group("Unicommerce (live)", [
							{ label: "Catalogue items", value: r2.message.catalogue_items },
							{ label: "Facilities", value: r2.message.facilities },
						], "remote");
					},
					error: function () {
						var target = document.getElementById("uc-side-stats");
						if (target) {
							target.innerHTML =
								'<div class="uc-stat-group-title">Unicommerce (live) &mdash; failed to load</div>';
						}
					},
				});
			},
		});
	}

	// ------------------------------------------------------------------ logs

	function load_logs() {
		frappe.call({
			method: "alaiy_os_connector_unicommerce.api.dashboard.get_recent_logs",
			callback: function (r) {
				var rows = r.message || [];
				var el = document.getElementById("uc-logs");
				if (!rows.length) {
					el.innerHTML = '<p class="uc-muted">No syncs recorded yet.</p>';
					return;
				}
				var html = '<table class="uc-log-table"><thead><tr>' +
					"<th>Type</th><th>Trigger</th><th>Status</th><th>Started</th>" +
					"<th class=\"uc-num\">Processed</th><th class=\"uc-num\">Created</th><th class=\"uc-num\">Failed</th>" +
					"</tr></thead><tbody>";
				rows.forEach(function (row) {
					html += '<tr data-log="' + frappe.utils.escape_html(row.name) + '">' +
						"<td>" + (row.sync_type || "&mdash;") + "</td>" +
						"<td>" + (row.trigger || "&mdash;") + "</td>" +
						'<td><span class="uc-status uc-status-' + (row.status || "unknown") + '">' +
							(row.status || "unknown") + "</span></td>" +
						"<td>" + (row.started_at ? frappe.datetime.str_to_user(row.started_at) : "&mdash;") + "</td>" +
						'<td class="uc-num">' + (row.items_processed || 0) + "</td>" +
						'<td class="uc-num">' + (row.items_created || 0) + "</td>" +
						'<td class="uc-num">' + (row.items_failed || 0) + "</td>" +
						"</tr>";
				});
				el.innerHTML = html + "</tbody></table>";
				$(el).find("tr[data-log]").on("click", function () {
					frappe.set_route("Form", "Unicommerce Sync Log", $(this).data("log"));
				});
			},
		});
	}

	// --------------------------------------------------------------- wiring

	document.getElementById("uc-test-btn").addEventListener("click", test_connection);

	document.getElementById("uc-pull-btn").addEventListener("click", function () {
		enqueue("alaiy_os_connector_unicommerce.api.sync.trigger_pull_sync",
			"uc-pull-btn", "uc-pull-log", "Pulling");
	});

	document.getElementById("uc-catalogue-btn").addEventListener("click", function () {
		enqueue("alaiy_os_connector_unicommerce.api.dashboard.trigger_catalogue_import",
			"uc-catalogue-btn", "uc-products-log", "Importing");
	});

	document.getElementById("uc-categories-btn").addEventListener("click", function () {
		enqueue("alaiy_os_connector_unicommerce.api.dashboard.trigger_item_group_sync",
			"uc-categories-btn", "uc-categories-log", "Syncing");
	});

	/* Pushing items WRITES to the Unicommerce tenant, which on a live account
	   is visible to the marketplaces immediately. Confirm, and name the tenant
	   in the prompt so it is obvious which account is about to be written to. */
	document.getElementById("uc-push-items-btn").addEventListener("click", function () {
		frappe.db.get_single_value("Unicommerce Connector Settings", "unicommerce_site").then(function (site) {
			frappe.confirm(
				"This <b>writes to Unicommerce</b> at <b>" + frappe.utils.escape_html(site || "the configured tenant") +
					"</b>.<br><br>Every Item flagged <i>Sync to Unicommerce</i> will be created or updated there. " +
					"On a live account those changes reach the connected marketplaces.<br><br>Continue?",
				function () {
					enqueue("alaiy_os_connector_unicommerce.api.sync.trigger_push_sync",
						"uc-push-items-btn", "uc-products-log", "Pushing");
				}
			);
		});
	});

	document.getElementById("uc-view-groups-btn").addEventListener("click", function () {
		frappe.set_route("List", "Item Group");
	});

	document.getElementById("uc-warehouses-btn").addEventListener("click", function () {
		frappe.set_route("Form", "Unicommerce Connector Settings");
	});

	$(page.body).find("[data-route-list]").on("click", function () {
		frappe.set_route("List", $(this).data("route-list"));
	});

	render_connector_status();
	load_stats();
	load_logs();
};
