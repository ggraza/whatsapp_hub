frappe.ui.form.on("WhatsApp Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Gateway"), () => {
			frappe.call({ method: "whatsapp_hub.api.ping_gateway", freeze: true }).then((r) => {
				frappe.msgprint(r.message || __("OK"));
			});
		});
		frm.add_custom_button(__("Open WhatsApp Hub"), () => frappe.set_route("whatsapp-hub"));
	},
});
