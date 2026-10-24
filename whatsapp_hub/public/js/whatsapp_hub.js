frappe.provide("whatsapp_hub");

whatsapp_hub.SKIP = ["WhatsApp Settings", "WhatsApp Account", "WhatsApp Group", "WhatsApp Message Log"];

$(document).on("form-refresh", function (e, frm) {
	const b = frappe.boot.whatsapp_hub;
	if (!b || !b.enabled || !b.can_send || !frm || frm.is_new()) return;
	if (whatsapp_hub.SKIP.includes(frm.doctype) || frm.meta.issingle || frm.meta.istable) return;
	frm.add_custom_button(__("WhatsApp"), () => whatsapp_hub.open_dialog(frm), __("Send"));
});

whatsapp_hub.open_dialog = async function (frm) {
	const info = await frappe.xcall("whatsapp_hub.api.resolve_recipients", { doctype: frm.doctype, name: frm.docname });
	const files = (frm.get_files ? frm.get_files() : []).filter((f) => f.file_url);
	const fields = [
		{ fieldname: "account", label: __("From Account"), fieldtype: "Link", options: "WhatsApp Account", reqd: 1,
			default: info.account, get_query: () => ({ filters: { enabled: 1, status: "Connected" } }) },
		{ fieldname: "numbers", label: __("Numbers (one per line, with country code)"), fieldtype: "Small Text",
			default: (info.numbers || []).slice(0, 1).join("\n"),
			description: info.party ? __("{0}: {1}", [__(info.party_type), info.party]) : "" },
	];
	if ((info.groups || []).length) {
		fields.push({ fieldname: "groups", label: __("Groups"), fieldtype: "MultiCheck", columns: 1,
			options: info.groups.map((g) => ({ label: g.subject || g.jid, value: g.name, checked: 0 })) });
	}
	fields.push(
		{ fieldname: "message", label: __("Message"), fieldtype: "Text", default: `${__(frm.doctype)} ${frm.docname}` },
		{ fieldname: "attach_print", label: __("Attach PDF"), fieldtype: "Check", default: 1 },
		{ fieldname: "print_format", label: __("Print Format"), fieldtype: "Link", options: "Print Format",
			depends_on: "attach_print", get_query: () => ({ filters: { doc_type: frm.doctype } }) }
	);
	if (files.length) {
		fields.push({ fieldname: "file_urls", label: __("Attached Files"), fieldtype: "MultiCheck", columns: 1,
			options: files.map((f) => ({ label: f.file_name, value: f.file_url, checked: 0 })) });
	}
	const d = new frappe.ui.Dialog({
		title: __("Send via WhatsApp"),
		fields,
		primary_action_label: __("Send"),
		primary_action(v) {
			frappe.xcall("whatsapp_hub.api.send_from_form", {
				account: v.account, reference_doctype: frm.doctype, reference_name: frm.docname,
				message: v.message, numbers: v.numbers, groups: JSON.stringify(v.groups || []),
				attach_print: v.attach_print ? 1 : 0, print_format: v.print_format,
				file_urls: JSON.stringify(v.file_urls || []),
			}).then((n) => {
				d.hide();
				frappe.show_alert({ message: __("{0} message(s) queued", [n]), indicator: "green" });
			});
		},
	});
	d.show();
};
