import frappe
from frappe.utils import add_days, now


def clear_old_logs():
	days = frappe.db.get_single_value("WhatsApp Settings", "log_retention_days") or 0
	if days > 0:
		frappe.db.delete("WhatsApp Message Log", {"creation": ["<", add_days(now(), -days)]})


def sync_status():
	"""Reconcile account status with the gateway (covers gateway restarts / missed webhooks)."""
	from whatsapp_hub.utils import GatewayError, gateway, is_enabled

	if not is_enabled():
		return
	for acc in frappe.get_all(
		"WhatsApp Account", filters={"enabled": 1, "status": ["!=", "Disconnected"]}, fields=["name", "status"]
	):
		try:
			res = gateway("GET", f"/sessions/{acc.name}/status", timeout=10)
			status = res.get("status") or "Disconnected"
		except GatewayError:
			status = "Failed"
		if status != acc.status and not (acc.status == "QR Pending" and status == "Starting"):
			frappe.db.set_value("WhatsApp Account", acc.name, "status", status)
	frappe.db.commit()
