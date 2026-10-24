import re

import frappe
from frappe import _
from frappe.model.document import Document


class WhatsAppAccount(Document):
	def autoname(self):
		sid = (self.session_id or "").strip().lower()
		if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,39}", sid):
			frappe.throw(_("Session ID must be 2-40 chars: letters, numbers, - or _"))
		self.session_id = self.name = sid

	def validate(self):
		if self.is_default and not self.enabled:
			frappe.throw(_("A default account must be enabled"))
		if self.is_default:
			frappe.db.sql("update `tabWhatsApp Account` set is_default=0 where name != %s", self.name)

	def on_trash(self):
		from whatsapp_hub.utils import gateway, is_enabled

		if is_enabled():
			try:
				gateway("POST", f"/sessions/{self.name}/logout", timeout=10)
			except Exception:
				pass
