import frappe
from frappe import _
from frappe.model.document import Document


class WhatsAppMessageLog(Document):
	@frappe.whitelist()
	def retry(self):
		frappe.only_for(("System Manager", "WhatsApp Manager"))
		if self.status != "Failed":
			frappe.throw(_("Only failed messages can be retried"))
		self.db_set({"status": "Queued", "error": None})
		frappe.enqueue(
			"whatsapp_hub.utils.deliver", queue="short", log_name=self.name, enqueue_after_commit=True
		)
