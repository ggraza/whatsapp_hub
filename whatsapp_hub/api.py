import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from whatsapp_hub import utils
from whatsapp_hub.utils import GatewayError


def _manager():
	frappe.only_for(("System Manager", "WhatsApp Manager"))


def _sender():
	frappe.only_for(utils.SEND_ROLES)


def _gw(*a, **kw):
	try:
		return utils.gateway(*a, **kw)
	except GatewayError as e:
		frappe.throw(str(e), title=_("WhatsApp Gateway"))


# ------------------------------------------------------------ admin / page
@frappe.whitelist()
def ping_gateway():
	_manager()
	res = _gw("GET", "/health", timeout=8)
	return _("Gateway OK — {0} active session(s)").format(res.get("sessions", 0))


@frappe.whitelist()
def get_accounts():
	_sender()
	return frappe.get_all(
		"WhatsApp Account",
		fields=["name", "label", "enabled", "is_default", "status", "phone_number", "last_connected", "last_error", "company"],
		order_by="creation asc",
	)


@frappe.whitelist()
def create_account(session_id, label, company=None):
	_manager()
	doc = frappe.get_doc(
		{"doctype": "WhatsApp Account", "session_id": session_id, "label": label, "company": company, "enabled": 1}
	).insert()
	return doc.name


@frappe.whitelist()
def start_session(account):
	_manager()
	acc = frappe.get_doc("WhatsApp Account", account)
	if not acc.enabled:
		frappe.throw(_("Account is disabled"))
	acc.db_set({"status": "Starting", "started_by": frappe.session.user, "last_error": None})
	try:
		utils.gateway("POST", f"/sessions/{acc.name}/start", {"webhook": utils.webhook_url()})
	except GatewayError as e:
		acc.db_set({"status": "Failed", "last_error": str(e)[:500]})
		frappe.db.commit()
		frappe.throw(str(e), title=_("WhatsApp Gateway"))


@frappe.whitelist()
def logout_session(account):
	_manager()
	_gw("POST", f"/sessions/{account}/logout")
	frappe.db.set_value("WhatsApp Account", account, {"status": "Disconnected", "phone_number": None})


@frappe.whitelist()
def sync_groups(account):
	_manager()
	acc = utils.get_account(account)
	groups = _gw("GET", f"/sessions/{acc.name}/groups", timeout=60).get("groups", [])
	for g in groups:
		name = frappe.db.get_value("WhatsApp Group", {"account": acc.name, "jid": g["jid"]})
		vals = {"subject": g.get("subject"), "participants": g.get("participants")}
		if name:
			frappe.db.set_value("WhatsApp Group", name, vals)
		else:
			frappe.get_doc({"doctype": "WhatsApp Group", "account": acc.name, "jid": g["jid"], **vals}).insert()
	return len(groups)


@frappe.whitelist()
def send_test(account, number, message):
	_manager()
	acc = utils.get_account(account)
	return utils.dispatch(acc.name, [number], message or "Test message from ERPNext")


# ------------------------------------------------------------ form dialog
@frappe.whitelist()
def resolve_recipients(doctype, name):
	_sender()
	frappe.has_permission(doctype, "read", name, throw=True)
	doc = frappe.get_doc(doctype, name)
	pt, p = utils.party_from_doc(doc)
	acc = frappe.db.get_value("WhatsApp Account", {"enabled": 1, "is_default": 1, "status": "Connected"}) or \
		frappe.db.get_value("WhatsApp Account", {"enabled": 1, "status": "Connected"})
	return {
		"party_type": pt,
		"party": p,
		"numbers": utils.get_party_numbers(pt, p) if pt else [],
		"groups": utils.get_party_groups(pt, p) if pt else [],
		"account": acc,
	}


@frappe.whitelist()
def send_from_form(account, reference_doctype, reference_name, message=None, numbers=None, groups=None,
		attach_print=0, print_format=None, file_urls=None):
	_sender()
	frappe.has_permission(reference_doctype, "read", reference_name, throw=True)
	numbers = [n for n in (frappe.parse_json(numbers) if isinstance(numbers, str) and numbers.startswith("[") else
		(numbers or "").replace(",", "\n").splitlines()) if str(n).strip()]
	groups = frappe.parse_json(groups) if groups else []
	file_urls = frappe.parse_json(file_urls) if file_urls else []

	attachments = []
	if int(attach_print or 0):
		pdf = frappe.attach_print(reference_doctype, reference_name, file_name=reference_name, print_format=print_format or None)
		attachments.append(utils.save_file(pdf["fname"], pdf["fcontent"]))
	for url in file_urls:
		if not frappe.db.exists("File", {"file_url": url, "attached_to_doctype": reference_doctype, "attached_to_name": reference_name}):
			frappe.throw(_("File {0} is not attached to this document").format(url))
		attachments.append(url)
	if not (message or attachments):
		frappe.throw(_("Nothing to send"))

	pt, p = utils.party_from_doc(frappe.get_doc(reference_doctype, reference_name))
	ref = {"reference_doctype": reference_doctype, "reference_name": reference_name, "party_type": pt, "party": p}
	count = 0
	if numbers:
		count += len(utils.dispatch(utils.get_account(account).name, numbers, message, attachments, **ref))
	for g in groups:
		grp = frappe.db.get_value("WhatsApp Group", g, ["jid", "account"], as_dict=True)
		if grp:
			count += len(utils.dispatch(utils.get_account(grp.account).name, [grp.jid], message, attachments, **ref))
	if not count:
		frappe.throw(_("No valid recipients"))
	return count


# ------------------------------------------------------------ gateway webhook
@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook():
	if not utils.verify_secret(frappe.get_request_header("X-Api-Secret")):
		frappe.throw(_("Unauthorized"), frappe.AuthenticationError)
	data = frappe.parse_json(frappe.request.get_data(as_text=True))
	frappe.set_user("Administrator")
	acc, event = data.get("session"), data.get("event")
	if not acc or not frappe.db.exists("WhatsApp Account", acc):
		return {"ok": False}

	if event == "qr":
		user = frappe.db.get_value("WhatsApp Account", acc, "started_by")
		if user:
			frappe.publish_realtime("whatsapp_hub_qr", {"account": acc, "qr": data.get("qr")}, user=user)
		frappe.cache.set_value(f"whatsapp_hub_qr:{acc}", data.get("qr"), expires_in_sec=120)
		frappe.db.set_value("WhatsApp Account", acc, "status", "QR Pending")
	elif event == "status":
		status = data.get("status")
		vals = {"status": status, "last_error": (data.get("error") or "")[:500] or None}
		if data.get("phone"):
			vals["phone_number"] = data["phone"]
		if status == "Connected":
			vals["last_connected"] = now_datetime()
		frappe.db.set_value("WhatsApp Account", acc, vals)
		frappe.publish_realtime(
			"whatsapp_hub_status",
			{"account": acc, "status": status, "phone": data.get("phone"), "error": data.get("error")},
			after_commit=True,
		)
	elif event == "message_status":
		log = frappe.db.get_value("WhatsApp Message Log", {"message_id": data.get("message_id")}, ["name", "status"], as_dict=True)
		new = data.get("status")
		if log and utils.RANK.get(new, 0) > utils.RANK.get(log.status, 0):
			frappe.db.set_value("WhatsApp Message Log", log.name, "status", new)
	elif event == "incoming" and utils.get_settings().log_incoming:
		frappe.get_doc({
			"doctype": "WhatsApp Message Log", "account": acc, "direction": "Incoming", "status": "Received",
			"recipient_type": "Group" if data.get("is_group") else "Individual",
			"recipient": data.get("from"), "message": data.get("text"), "message_id": data.get("message_id"),
		}).insert(ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def get_qr(account):
	"""Polling fallback for the QR dialog (works when websockets are blocked, e.g. behind a proxy)."""
	_manager()
	status, phone, error = frappe.db.get_value("WhatsApp Account", account, ["status", "phone_number", "last_error"])
	qr = None
	try:
		live = utils.gateway("GET", f"/sessions/{account}/qr", timeout=8)
		qr = live.get("qr")
		status = live.get("status") or status
		phone = live.get("phone") or phone
	except GatewayError as e:
		error = str(e)
	if not qr and status == "QR Pending":
		qr = frappe.cache.get_value(f"whatsapp_hub_qr:{account}")
	return {"qr": qr, "status": status, "phone": phone, "error": error}
