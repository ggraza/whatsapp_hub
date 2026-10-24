import frappe
from frappe import _
from frappe.model.document import Document


class WhatsAppSettings(Document):
	def validate(self):
		self.gateway_url = (self.gateway_url or "").strip().rstrip("/")
		self.default_country_code = "".join(c for c in (self.default_country_code or "") if c.isdigit())
		if self.enabled:
			if not self.gateway_url:
				frappe.throw(_("Gateway URL is required"))
			if not self.get_password("api_secret", raise_exception=False):
				frappe.throw(_("API Secret is required"))
