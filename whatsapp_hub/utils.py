import base64
import hashlib
import mimetypes
import re

import frappe
import requests
from frappe import _
from frappe.utils import get_url

PARTY_TYPES = ("Customer", "Supplier", "Employee")
SEND_ROLES = ("System Manager", "WhatsApp Manager", "WhatsApp User")
RANK = {"Queued": 0, "Failed": 0, "Sent": 1, "Delivered": 2, "Read": 3}


class GatewayError(Exception):
	pass


# ---------------------------------------------------------------- settings
def get_settings():
	return frappe.get_single("WhatsApp Settings")


def is_enabled():
	return bool(frappe.db.get_single_value("WhatsApp Settings", "enabled"))


def boot_session(bootinfo):
	try:
		bootinfo.whatsapp_hub = {
			"enabled": is_enabled(),
			"can_send": bool(set(frappe.get_roles()) & set(SEND_ROLES)),
		}
	except Exception:
		bootinfo.whatsapp_hub = {"enabled": False, "can_send": False}


def webhook_url():
	base = get_settings().site_url or get_url()
	return base.rstrip("/") + "/api/method/whatsapp_hub.api.webhook"


# ---------------------------------------------------------------- gateway
def gateway(method, path, payload=None, timeout=30):
	s = get_settings()
	if not s.enabled:
		frappe.throw(_("WhatsApp integration is disabled in WhatsApp Settings"))
	url = (s.gateway_url or "").rstrip("/") + path
	try:
		r = requests.request(
			method,
			url,
			json=payload,
			headers={"x-api-secret": s.get_password("api_secret", raise_exception=False) or ""},
			timeout=timeout,
		)
	except requests.RequestException as e:
		raise GatewayError(f"Gateway unreachable: {e}") from e
	if not r.ok:
		try:
			msg = r.json().get("error")
		except Exception:
			msg = r.text[:300]
		raise GatewayError(msg or f"Gateway HTTP {r.status_code}")
	return r.json()


# ---------------------------------------------------------------- numbers & parties
def normalize_number(raw):
	"""Return digits in international format (no +), or a group JID untouched."""
	if not raw:
		return None
	raw = str(raw).strip()
	if raw.endswith("@g.us"):
		return raw
	digits = re.sub(r"\D", "", raw)
	if not digits:
		return None
	cc = get_settings().default_country_code or ""
	if digits.startswith("00"):
		digits = digits[2:]
	elif digits.startswith("0") and cc:
		digits = cc + digits.lstrip("0")
	return digits if 8 <= len(digits) <= 15 else None


def get_party_numbers(party_type, party, first_only=False):
	if party_type not in PARTY_TYPES or not party or not frappe.db.exists(party_type, party):
		return []
	raw = []
	if party_type == "Employee":
		raw.append(frappe.db.get_value("Employee", party, "cell_number"))
	else:
		raw.append(frappe.db.get_value(party_type, party, "mobile_no"))
		contacts = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "link_doctype": party_type, "link_name": party},
			pluck="parent",
		)
		if contacts:
			rows = frappe.get_all(
				"Contact Phone",
				filters={"parent": ["in", contacts]},
				fields=["phone"],
				order_by="is_primary_mobile_no desc, is_primary_phone desc",
			)
			raw += [r.phone for r in rows]
	out = []
	for n in map(normalize_number, raw):
		if n and n not in out:
			out.append(n)
	return out[:1] if first_only else out


def get_party_groups(party_type, party, account=None):
	filters = {"party_type": party_type, "party": party}
	if account:
		filters["account"] = account
	return frappe.get_all("WhatsApp Group", filters=filters, fields=["name", "jid", "subject", "account"])


def party_from_doc(doc):
	pt, p = doc.get("party_type"), doc.get("party")
	if pt in PARTY_TYPES and p:
		return pt, p
	for dt, field in (("Customer", "customer"), ("Supplier", "supplier"), ("Employee", "employee")):
		if doc.get(field):
			return dt, doc.get(field)
	if doc.doctype in PARTY_TYPES:
		return doc.doctype, doc.name
	return None, None


# ---------------------------------------------------------------- accounts
def get_account(name=None, require_connected=True):
	if not name:
		name = frappe.db.get_value(
			"WhatsApp Account", {"enabled": 1, "is_default": 1, "status": "Connected"}
		) or frappe.db.get_value("WhatsApp Account", {"enabled": 1, "status": "Connected"})
		if not name:
			frappe.throw(_("No connected WhatsApp account available"))
	acc = frappe.get_doc("WhatsApp Account", name)
	if not acc.enabled:
		frappe.throw(_("WhatsApp Account {0} is disabled").format(name))
	if require_connected and acc.status != "Connected":
		frappe.throw(_("WhatsApp Account {0} is not connected").format(name))
	return acc


# ---------------------------------------------------------------- sending
def save_file(fname, content):
	f = frappe.get_doc(
		{"doctype": "File", "file_name": fname, "content": content, "is_private": 1}
	).insert(ignore_permissions=True)
	return f.file_url


def queue_message(account, recipient, message, attachment_url=None, **ref):
	if not is_enabled():
		frappe.throw(_("WhatsApp integration is disabled in WhatsApp Settings"))
	to = normalize_number(recipient)
	if not to:
		frappe.throw(_("Invalid WhatsApp number: {0}").format(recipient))
	log = frappe.get_doc(
		{
			"doctype": "WhatsApp Message Log",
			"account": account,
			"direction": "Outgoing",
			"status": "Queued",
			"recipient_type": "Group" if to.endswith("@g.us") else "Individual",
			"recipient": to,
			"message": message,
			"attachment": attachment_url,
			**ref,
		}
	).insert(ignore_permissions=True)
	frappe.enqueue(
		"whatsapp_hub.utils.deliver", queue="short", log_name=log.name, enqueue_after_commit=True
	)
	return log.name


def dispatch(account, recipients, message, attachment_urls=None, **ref):
	"""One log row per recipient per attachment; caption goes on the first only."""
	names, seen = [], set()
	for r in recipients:
		to = normalize_number(r)
		if not to or to in seen:
			continue
		seen.add(to)
		for i, url in enumerate(attachment_urls or [None]):
			names.append(queue_message(account, to, message if i == 0 else "", url, **ref))
	return names


def deliver(log_name):
	log = frappe.get_doc("WhatsApp Message Log", log_name)
	if log.status != "Queued":
		return
	try:
		acc = get_account(log.account)
		payload = {"to": log.recipient, "text": log.message or ""}
		if log.attachment:
			f = frappe.get_doc("File", {"file_url": log.attachment})
			content = f.get_content()
			if isinstance(content, str):
				content = content.encode()
			limit = (get_settings().max_attachment_mb or 15) * 1024 * 1024
			if len(content) > limit:
				frappe.throw(_("Attachment exceeds the {0} MB limit").format(limit // 1024 // 1024))
			payload["media"] = {
				"filename": f.file_name,
				"mimetype": mimetypes.guess_type(f.file_name)[0] or "application/octet-stream",
				"content_base64": base64.b64encode(content).decode(),
			}
		res = gateway("POST", f"/sessions/{acc.name}/send", payload, timeout=120)
		log.db_set({"status": "Sent", "message_id": res.get("message_id"), "error": None})
	except Exception as e:
		frappe.db.rollback()
		log.db_set({"status": "Failed", "error": str(e)[:1000]})
	frappe.db.commit()


def verify_secret(provided):
	secret = get_settings().get_password("api_secret", raise_exception=False) or ""
	if not secret or not provided:
		return False
	a = hashlib.sha256(secret.encode()).digest()
	b = hashlib.sha256(provided.encode()).digest()
	import hmac

	return hmac.compare_digest(a, b)
