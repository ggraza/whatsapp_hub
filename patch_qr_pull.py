"""Run from the whatsapp_hub repo root:  python3 patch_qr_pull.py
Makes get_qr ask the gateway directly for the QR (no dependency on webhook / cache / websocket)."""
import os, re

assert os.path.exists("pyproject.toml"), "run from the repo root"
SRV = "gateway/server.js"
API = "whatsapp_hub/api.py"

# ---------------- gateway/server.js ----------------
s = open(SRV).read()
if "/sessions/:id/qr" not in s:
    a = "emit(s, id, { event: 'qr', qr: await QRCode.toDataURL(qr, { margin: 1, width: 320 }) });"
    b = "s.retries = 0;"
    c = "app.post('/sessions/:id/logout'"
    for x in (a, b, c):
        assert x in s, f"not found in server.js: {x[:50]}"
    s = s.replace(a, "s.qr = await QRCode.toDataURL(qr, { margin: 1, width: 320 });\n      emit(s, id, { event: 'qr', qr: s.qr });", 1)
    s = s.replace(b, "s.retries = 0; s.qr = null;", 1)
    route = """app.get('/sessions/:id/qr', wrap(async (req, res) => {
  const s = sessions.get(req.params.id);
  res.json({ status: s?.status || 'Disconnected', phone: s?.phone || null, qr: s?.status === 'QR Pending' ? s.qr || null : null });
}));

"""
    s = s.replace(c, route + c, 1)
    open(SRV, "w").write(s)

# ---------------- api.py ----------------
t = open(API).read()
assert "def get_qr" in t, "apply patch_qr_polling.py first"
if "/qr" not in t.split("def get_qr", 1)[1]:
    pat = r'(def get_qr\(account\):.*?)(\n\tstatus, phone, error = [^\n]*\n)(.*?)(\treturn \{"qr": qr[^\n]*\n)'
    m = re.search(pat, t, flags=re.S)
    assert m, "get_qr body not recognised"
    body = '''	qr = None
	try:
		live = utils.gateway("GET", f"/sessions/{account}/qr", timeout=8)
		qr = live.get("qr")
		status = live.get("status") or status
		phone = live.get("phone") or phone
	except GatewayError as e:
		error = str(e)
	if not qr and status == "QR Pending":
		qr = frappe.cache.get_value(f"whatsapp_hub_qr:{account}")
'''
    t = t[: m.start(3)] + body + t[m.start(4):]
    open(API, "w").write(t)
print("patched server.js and api.py")
