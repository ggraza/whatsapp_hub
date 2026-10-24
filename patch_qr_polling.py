"""Run from the whatsapp_hub repo root (folder with pyproject.toml):  python3 patch_qr_polling.py"""
import os

assert os.path.exists("pyproject.toml"), "run from the repo root"
API = "whatsapp_hub/api.py"
JS = "whatsapp_hub/whatsapp_hub/page/whatsapp_hub/whatsapp_hub.js"

# ---------------- api.py ----------------
s = open(API).read()
if "def get_qr" not in s:
    old = '\t\tfrappe.db.set_value("WhatsApp Account", acc, "status", "QR Pending")\n'
    assert old in s, "QR branch not found in api.py"
    new = (
        '\t\tfrappe.cache.set_value(f"whatsapp_hub_qr:{acc}", data.get("qr"), expires_in_sec=120)\n' + old
    )
    s = s.replace(old, new, 1)
    s = s.rstrip("\n") + '''


@frappe.whitelist()
def get_qr(account):
	"""Polling fallback for the QR dialog (works when websockets are blocked, e.g. behind a proxy)."""
	_manager()
	status, phone, error = frappe.db.get_value("WhatsApp Account", account, ["status", "phone_number", "last_error"])
	qr = frappe.cache.get_value(f"whatsapp_hub_qr:{account}") if status == "QR Pending" else None
	return {"qr": qr, "status": status, "phone": phone, "error": error}
'''
    open(API, "w").write(s)

# ---------------- page js ----------------
j = open(JS).read()
if "poll_qr" not in j:
    a = "on_hide: () => { this.qr_dialog = null; },"
    b = 'frappe.xcall("whatsapp_hub.api.start_session", { account: name }).catch(() => this.qr_dialog && this.qr_dialog.hide());'
    c = "\n\ton_qr(d) {"
    for x in (a, b, c):
        assert x in j, f"not found in page js: {x[:40]}"
    j = j.replace(a, "on_hide: () => { clearInterval(this._poll); this.qr_dialog = null; },", 1)
    j = j.replace(
        b,
        'frappe.xcall("whatsapp_hub.api.start_session", { account: name })\n'
        "\t\t\t.then(() => this.poll_qr(name))\n"
        "\t\t\t.catch(() => this.qr_dialog && this.qr_dialog.hide());",
        1,
    )
    method = """
	poll_qr(name) {
		clearInterval(this._poll);
		this._last_qr = null;
		this._poll = setInterval(() => {
			if (!this.qr_dialog) return clearInterval(this._poll);
			frappe.xcall("whatsapp_hub.api.get_qr", { account: name }).then((r) => {
				if (!this.qr_dialog) return;
				if (r.qr && r.qr !== this._last_qr) {
					this._last_qr = r.qr;
					this.on_qr({ account: name, qr: r.qr });
				}
				if (["Connected", "Disconnected", "Failed"].includes(r.status)) {
					clearInterval(this._poll);
					this.on_status({ account: name, status: r.status, phone: r.phone, error: r.error });
				}
			});
		}, 2000);
	}
"""
    j = j.replace(c, method + c, 1)
    open(JS, "w").write(j)
print("patched api.py and whatsapp_hub.js")
