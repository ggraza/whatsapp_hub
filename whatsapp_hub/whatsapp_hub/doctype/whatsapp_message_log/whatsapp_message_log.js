frappe.ui.form.on("WhatsApp Message Log", {
	refresh(frm) {
		if (frm.doc.status === "Failed") {
			frm.add_custom_button(__("Retry"), () =>
				frm.call("retry").then(() => frm.reload_doc())
			);
		}
	},
});
