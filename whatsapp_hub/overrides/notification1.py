import html
import re

import frappe
from frappe.email.doctype.notification.notification import Notification

from whatsapp_hub import utils


class WhatsAppNotification(Notification):
	"""Adds a 'WhatsApp' channel to the standard Notification doctype."""

	def send(self, doc):
		if self.channel != "WhatsApp":
			return super().send(doc)
		try:
			self.send_whatsapp(doc)
		except Exception:
			frappe.log_error(title=f"WhatsApp Notification failed: {self.name}")

	def send_whatsapp(self, doc):
		if not utils.is_enabled():
			return
		context = {"doc": doc, "alert": self, "comments": None, "nowdate": frappe.utils.nowdate()}
		text = frappe.render_template(self.message or self.subject or "", context)
		if self.message_type == "HTML":
			text = html.unescape(re.sub(r"<br\s*/?>|</p>", "\n", text))
			text = re.sub(r"<[^>]+>", "", text).strip()

		attachments = []
		if self.attach_print:
			pdf = frappe.get_print(
				doc.doctype, doc.name, self.print_format or None, as_pdf=True,
				pdf_options={"load-error-handling": "ignore", "load-media-error-handling": "ignore"},
			)
			attachments.append(utils.save_file(f'{doc.name.replace("/", "-")}.pdf', pdf))

		party_type, party = utils.party_from_doc(doc)
		ref = {
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"party_type": party_type,
			"party": party,
			"notification": self.name,
		}

		# 1) numbers from recipient rows + party -> via the chosen (or default) account
		numbers = self.get_numbers(doc, context)
		if self.whatsapp_send_to_party and party:
			numbers += utils.get_party_numbers(party_type, party, first_only=True)
		if numbers:
			acc = utils.get_account(self.whatsapp_account or None)
			utils.dispatch(acc.name, numbers, text, attachments, **ref)

		# 2) groups: always sent from the account that owns the group
		groups = []
		if self.whatsapp_group:
			groups.append(frappe.db.get_value("WhatsApp Group", self.whatsapp_group, ["jid", "account"], as_dict=True))
		if self.whatsapp_send_to_party_groups and party:
			groups += utils.get_party_groups(party_type, party, self.whatsapp_account or None)
		for g in groups:
			if g:
				utils.dispatch(utils.get_account(g.account).name, [g.jid], text, attachments, **ref)

	def get_numbers(self, doc, context):
		numbers = []
		for r in self.recipients or []:
			if r.condition and not frappe.safe_eval(r.condition, None, context):
				continue
			field = r.receiver_by_document_field
			if field == "owner":
				numbers.append(frappe.db.get_value("User", doc.get("owner"), "mobile_no"))
			elif field:
				numbers.append(doc.get(field))
			if r.receiver_by_role:
				users = frappe.get_all("Has Role", filters={"role": r.receiver_by_role, "parenttype": "User"}, pluck="parent")
				numbers += frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="mobile_no")
		return [n for n in numbers if n]
