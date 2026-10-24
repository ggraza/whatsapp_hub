import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

ROLES = ("WhatsApp Manager", "WhatsApp User")


def before_install():
	ensure_roles()


def ensure_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def setup():
	ensure_roles()
	add_notification_channel()
	cond = "eval:doc.channel=='WhatsApp'"
	create_custom_fields(
		{
			"Notification": [
				{
					"fieldname": "whatsapp_account",
					"fieldtype": "Link",
					"label": "WhatsApp Account",
					"options": "WhatsApp Account",
					"insert_after": "channel",
					"depends_on": cond,
					"description": "Empty = default connected account",
				},
				{
					"fieldname": "whatsapp_group",
					"fieldtype": "Link",
					"label": "WhatsApp Group",
					"options": "WhatsApp Group",
					"insert_after": "whatsapp_account",
					"depends_on": cond,
				},
				{
					"fieldname": "whatsapp_send_to_party",
					"fieldtype": "Check",
					"label": "Send to Party's WhatsApp Number",
					"insert_after": "whatsapp_group",
					"depends_on": cond,
					"description": "Customer / Supplier / Employee found on the document",
				},
				{
					"fieldname": "whatsapp_send_to_party_groups",
					"fieldtype": "Check",
					"label": "Send to Party's Linked WhatsApp Groups",
					"insert_after": "whatsapp_send_to_party",
					"depends_on": cond,
				},
			]
		},
		ignore_validate=True,
	)


def add_notification_channel():
	field = frappe.get_meta("Notification").get_field("channel")
	options = (field.options or "").split("\n")
	if "WhatsApp" not in options:
		options.append("WhatsApp")
		make_property_setter("Notification", "channel", "options", "\n".join(options), "Text")
