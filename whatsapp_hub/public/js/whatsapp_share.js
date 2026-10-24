frappe.provide("whatsapp_hub");

whatsapp_hub.SHARE_SKIP = ["WhatsApp Settings", "WhatsApp Account", "WhatsApp Group", "WhatsApp Message Log"];

$(document).on("form-refresh", function (e, frm) {
	const b = frappe.boot.whatsapp_hub;
	if (!b || !b.can_send || !frm || frm.is_new()) return;
	if (whatsapp_hub.SHARE_SKIP.includes(frm.doctype) || frm.meta.issingle || frm.meta.istable) return;
	frm.add_custom_button(__("WhatsApp (Image / App)"), () => whatsapp_hub.share_dialog(frm), __("Send"));
});

whatsapp_hub.normalize_phone = function (raw, cc) {
	let d = String(raw || "").replace(/\D/g, "");
	if (d.startsWith("00")) d = d.slice(2);
	else if (d.startsWith("0") && cc) d = cc + d.replace(/^0+/, "");
	return d;
};

whatsapp_hub.links = function (phone, message) {
	const q = "text=" + encodeURIComponent(message || "");
	return {
		web: phone ? `https://web.whatsapp.com/send?phone=${phone}&${q}` : `https://web.whatsapp.com/send?${q}`,
		app: phone ? `https://wa.me/${phone}?${q}` : `https://wa.me/?${q}`,
	};
};

whatsapp_hub.b64_to_blob = function (b64, type) {
	const bin = atob(b64);
	const arr = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
	return new Blob([arr], { type });
};

whatsapp_hub.share_dialog = async function (frm) {
	const info = await frappe.xcall("whatsapp_hub.share.get_share_info", { doctype: frm.doctype, name: frm.docname });
	const mobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
	let blob = null, file = null, objectUrl = null;

	const d = new frappe.ui.Dialog({
		title: __("Share via WhatsApp (Image)"),
		fields: [
			{ fieldname: "phone", fieldtype: "Data", label: __("WhatsApp Number (with country code)"),
				default: (info.numbers || [])[0] || "", description: info.party ? `${__(info.party_type)}: ${info.party}` : "" },
			{ fieldname: "print_format", fieldtype: "Link", options: "Print Format", label: __("Print Format"),
				default: frm.meta.default_print_format || "", get_query: () => ({ filters: { doc_type: frm.doctype } }) },
			{ fieldname: "message", fieldtype: "Text", label: __("Message"), default: info.message },
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: __("Create Image"),
		primary_action: (v) => create(v),
	});

	const values = () => {
		const phone = whatsapp_hub.normalize_phone(d.get_value("phone"), info.country_code);
		return { phone, message: d.get_value("message") || "" };
	};

	async function create(v) {
		d.disable_primary_action();
		try {
			const r = await frappe.xcall("whatsapp_hub.share.create_image", {
				doctype: frm.doctype, name: frm.docname, print_format: v.print_format || "",
			});
			blob = whatsapp_hub.b64_to_blob(r.image, "image/png");
			file = new File([blob], r.filename, { type: "image/png" });
			if (objectUrl) URL.revokeObjectURL(objectUrl);
			objectUrl = URL.createObjectURL(blob);
			render();
			d.set_primary_action(__("Re-create Image"), (x) => create(x));
		} finally {
			d.enable_primary_action();
		}
	}

	function render() {
		const canShare = !!(navigator.canShare && navigator.canShare({ files: [file] }));
		const btn = (act, label, cls = "btn-default") =>
			`<button type="button" class="btn btn-sm ${cls}" data-act="${act}" style="margin:4px 6px 0 0">${label}</button>`;
		const buttons = [
			canShare ? btn("share", __("Share…"), "btn-primary") : "",
			!mobile ? btn("web", __("Copy image & open WhatsApp Web"), canShare ? "btn-default" : "btn-primary") : "",
			btn("app", mobile ? __("Open WhatsApp (text only)") : __("Open wa.me link (text only)")),
			btn("download", __("Download image")),
		].join("");
		d.fields_dict.result.$wrapper.html(`
			<div style="text-align:center;margin-top:8px">
				<img src="${objectUrl}" style="max-width:100%;max-height:320px;border:1px solid var(--border-color);border-radius:6px">
			</div>
			<div style="margin-top:8px">${buttons}</div>
			<div class="text-muted small" style="margin-top:6px">
				${__("WhatsApp links cannot attach images. “Share…” attaches it on Android/iOS/Windows; on desktop the image is copied, then press Ctrl+V in the chat.")}
			</div>`);
		d.fields_dict.result.$wrapper.off("click").on("click", "[data-act]", (e) => act($(e.currentTarget).data("act")));
	}

	async function act(which) {
		const { phone, message } = values();
		const links = whatsapp_hub.links(phone, message);
		if (which === "share") {
			try { await navigator.share({ files: [file], text: message }); }
			catch (err) { if (err.name !== "AbortError") frappe.msgprint(String(err)); }
		} else if (which === "web") {
			try {
				await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
				frappe.show_alert({ message: __("Image copied. In WhatsApp press Ctrl+V to paste it."), indicator: "green" }, 8);
			} catch (err) {
				frappe.show_alert({ message: __("Browser could not copy the image. Use “Download image” and attach it manually."), indicator: "orange" }, 8);
			}
			window.open(links.web, "_blank", "noopener");
		} else if (which === "app") {
			window.open(links.app, "_blank", "noopener");
		} else if (which === "download") {
			const a = document.createElement("a");
			a.href = objectUrl; a.download = file.name; a.click();
		}
	}

	d.show();
};
