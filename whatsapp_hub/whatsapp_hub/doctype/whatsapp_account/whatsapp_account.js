frappe.ui.form.on("WhatsApp Account", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Link / Manage in WhatsApp Hub"), () => frappe.set_route("whatsapp-hub"));
		}
	},
});
