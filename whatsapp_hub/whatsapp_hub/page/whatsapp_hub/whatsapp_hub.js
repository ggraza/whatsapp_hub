frappe.provide("whatsapp_hub");

frappe.pages["whatsapp-hub"].on_page_load = function (wrapper) {
	new whatsapp_hub.Hub(wrapper);
};

whatsapp_hub.Hub = class Hub {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("WhatsApp Hub"), single_column: true });
		this.$body = $('<div class="wa-hub"></div>').appendTo(this.page.main);
		this.inject_css();
		this.page.set_primary_action(__("Link New Account"), () => this.add_account(), "add");
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Settings"), () => frappe.set_route("Form", "WhatsApp Settings"));
		this.page.add_menu_item(__("Message Log"), () => frappe.set_route("List", "WhatsApp Message Log"));
		this.page.add_menu_item(__("Groups"), () => frappe.set_route("List", "WhatsApp Group"));
		frappe.realtime.on("whatsapp_hub_qr", (d) => this.on_qr(d));
		frappe.realtime.on("whatsapp_hub_status", (d) => this.on_status(d));
		this.$body.on("click", "[data-action]", (e) => {
			const $b = $(e.currentTarget);
			this[$b.data("action")]($b.data("name"));
		});
		this.refresh();
	}

	inject_css() {
		if ($("#wa-hub-css").length) return;
		$(`<style id="wa-hub-css">
			.wa-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-top:12px}
			.wa-card{border:1px solid var(--border-color);border-radius:var(--border-radius-lg);padding:16px;background:var(--card-bg)}
			.wa-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:var(--gray-500)}
			.wa-dot.Connected{background:var(--green-500)}.wa-dot.Failed{background:var(--red-500)}
			.wa-dot.Starting,.wa-dot.QR\\ Pending{background:var(--orange-500)}
			.wa-actions{margin-top:12px;display:flex;flex-wrap:wrap;gap:6px}
			.wa-qr{width:300px;height:300px;margin:auto;display:flex;align-items:center;justify-content:center;border:1px solid var(--border-color);border-radius:8px}
			.wa-qr img{width:100%;height:100%}
		</style>`).appendTo("head");
	}

	refresh() {
		frappe.xcall("whatsapp_hub.api.get_accounts").then((rows) => {
			if (!rows.length) {
				this.$body.html(`<div class="text-muted text-center" style="padding:60px">${__("No WhatsApp accounts yet. Click “Link New Account” to scan a QR code.")}</div>`);
				return;
			}
			const e = frappe.utils.escape_html;
			const cards = rows.map((r) => {
				const connected = r.status === "Connected";
				return `<div class="wa-card">
					<div class="flex justify-between"><b>${e(r.label)}</b>
						<span><span class="wa-dot ${e(r.status)}"></span>${__(r.status)}</span></div>
					<div class="text-muted small">${e(r.name)}${r.is_default ? " · " + __("Default") : ""}${r.enabled ? "" : " · " + __("Disabled")}</div>
					<div style="margin-top:8px">${r.phone_number ? "+" + e(r.phone_number) : "<span class='text-muted'>" + __("Not linked") + "</span>"}</div>
					${r.last_error ? `<div class="text-danger small">${e(r.last_error)}</div>` : ""}
					<div class="wa-actions">
						${connected
							? `<button class="btn btn-xs btn-default" data-action="send_test" data-name="${e(r.name)}">${__("Send Test")}</button>
							   <button class="btn btn-xs btn-default" data-action="sync_groups" data-name="${e(r.name)}">${__("Sync Groups")}</button>
							   <button class="btn btn-xs btn-danger" data-action="logout" data-name="${e(r.name)}">${__("Log out")}</button>`
							: `<button class="btn btn-xs btn-primary" data-action="link" data-name="${e(r.name)}" ${r.enabled ? "" : "disabled"}>${__("Scan QR")}</button>`}
						<button class="btn btn-xs btn-default" data-action="open_doc" data-name="${e(r.name)}">${__("Edit")}</button>
					</div></div>`;
			});
			this.$body.html(`<div class="wa-grid">${cards.join("")}</div>`);
		});
	}

	open_doc(name) { frappe.set_route("Form", "WhatsApp Account", name); }

	add_account() {
		frappe.prompt(
			[
				{ fieldname: "session_id", label: __("Session ID"), fieldtype: "Data", reqd: 1, description: __("e.g. sales-1 (lowercase)") },
				{ fieldname: "label", label: __("Display Name"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
			],
			(v) => frappe.xcall("whatsapp_hub.api.create_account", v).then((name) => { this.refresh(); this.link(name); }),
			__("New WhatsApp Account"),
			__("Create & Link")
		);
	}

	link(name) {
		this.qr_name = name;
		this.qr_dialog = new frappe.ui.Dialog({
			title: __("Link WhatsApp — {0}", [name]),
			size: "large",
			on_hide: () => { this.qr_dialog = null; },
		});
		this.qr_dialog.$body.html(`<div class="row">
			<div class="col-md-6"><h4>${__("Use WhatsApp on your phone to link this account")}</h4>
				<ol style="line-height:2;padding-left:18px">
					<li>${__("Open WhatsApp on your phone")}</li>
					<li>${__("Tap Menu or Settings → Linked devices")}</li>
					<li>${__("Tap Link a device")}</li>
					<li>${__("Point your phone at this screen to scan the QR code")}</li>
				</ol>
				<div class="text-muted small wa-note"></div></div>
			<div class="col-md-6"><div class="wa-qr"><span class="text-muted">${__("Generating QR code…")}</span></div></div></div>`);
		this.qr_dialog.show();
		frappe.xcall("whatsapp_hub.api.start_session", { account: name }).catch(() => this.qr_dialog && this.qr_dialog.hide());
	}

	on_qr(d) {
		if (!this.qr_dialog || d.account !== this.qr_name) return;
		this.qr_dialog.$body.find(".wa-qr").html(`<img src="${d.qr}" alt="QR">`);
		this.qr_dialog.$body.find(".wa-note").text(__("QR codes refresh automatically. Keep this window open."));
	}

	on_status(d) {
		if (this.qr_dialog && d.account === this.qr_name) {
			if (d.status === "Connected") {
				this.qr_dialog.hide();
				frappe.show_alert({ message: __("Linked +{0}", [d.phone || ""]), indicator: "green" });
			} else if (d.status === "Disconnected" || d.status === "Failed") {
				this.qr_dialog.$body.find(".wa-qr").html(`<span class="text-danger">${frappe.utils.escape_html(d.error || __("QR expired. Close and try again."))}</span>`);
			}
		}
		clearTimeout(this._t);
		this._t = setTimeout(() => this.refresh(), 600);
	}

	logout(name) {
		frappe.confirm(__("Log out and unlink {0}?", [name]), () =>
			frappe.xcall("whatsapp_hub.api.logout_session", { account: name }).then(() => this.refresh())
		);
	}

	sync_groups(name) {
		frappe.xcall("whatsapp_hub.api.sync_groups", { account: name }).then((n) =>
			frappe.show_alert({ message: __("{0} groups synced", [n]), indicator: "green" })
		);
	}

	send_test(name) {
		frappe.prompt(
			[
				{ fieldname: "number", label: __("Number or Group JID"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "message", label: __("Message"), fieldtype: "Small Text", default: "Test from ERPNext" },
			],
			(v) => frappe.xcall("whatsapp_hub.api.send_test", { account: name, ...v }).then(() =>
				frappe.show_alert({ message: __("Queued"), indicator: "green" })),
			__("Send Test Message"),
			__("Send")
		);
	}
};
