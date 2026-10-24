import base64
import re
import shutil
import subprocess

import frappe
from frappe import _

from whatsapp_hub import utils

DEFAULT_TEMPLATE = """Thank you for your business.
Please find the details of your transaction.
Invoice No: {{ doc.name }}
We appreciate your trust and look forward to serving you again.
Regards,"""


def _check(doctype, name):
	frappe.only_for(utils.SEND_ROLES)
	frappe.has_permission(doctype, "read", name, throw=True)


def _absolute_urls(html):
	# spaces in image URLs (e.g. "logo new.jpeg") break the renderer
	html = re.sub(
		r'((?:src)=")([^"]*)(")', lambda m: m.group(1) + m.group(2).replace(" ", "%20") + m.group(3), html
	)
	try:
		from frappe.utils import scrub_urls

		return scrub_urls(html)
	except Exception:
		base = frappe.utils.get_url()
		return html.replace('src="/', f'src="{base}/').replace('href="/', f'href="{base}/')


@frappe.whitelist()
def get_share_info(doctype, name):
	_check(doctype, name)
	doc = frappe.get_doc(doctype, name)
	try:
		template = frappe.db.get_single_value("WhatsApp Settings", "share_message_template")
	except Exception:
		template = None
	message = frappe.render_template(template or DEFAULT_TEMPLATE, {"doc": doc})
	party_type, party = utils.party_from_doc(doc)
	return {
		"message": message,
		"party_type": party_type,
		"party": party,
		"numbers": utils.get_party_numbers(party_type, party) if party_type else [],
		"country_code": utils.get_settings().default_country_code or "",
	}


@frappe.whitelist()
def create_image(doctype, name, print_format=None):
	"""Render the print format to a PNG (wkhtmltoimage) and return it base64-encoded."""
	_check(doctype, name)
	exe = shutil.which("wkhtmltoimage")
	if not exe:
		frappe.throw(_("wkhtmltoimage is not installed on the server (it ships with the wkhtmltox package)."))
	html = _absolute_urls(frappe.get_print(doctype, name, print_format or None))
	cmd = [
		exe, "--quiet", "--format", "png", "--width", "900", "--zoom", "1.4", "--encoding", "utf-8",
		"--load-error-handling", "ignore", "--load-media-error-handling", "ignore", "-", "-",
	]
	try:
		proc = subprocess.run(cmd, input=html.encode("utf-8"), capture_output=True, timeout=90)
	except subprocess.TimeoutExpired:
		frappe.throw(_("Image generation timed out"))
	if not proc.stdout.startswith(b"\x89PNG"):
		err = proc.stderr.decode("utf-8", "replace")[-500:]
		frappe.log_error(title=f"WhatsApp image failed: {doctype} {name}", message=err)
		frappe.throw(_("Could not create the image: {0}").format(err[-200:]))
	return {
		"image": base64.b64encode(proc.stdout).decode(),
		"filename": f'{name.replace("/", "-")}.png',
	}
