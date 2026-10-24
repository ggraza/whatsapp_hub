# WhatsApp Hub for ERPNext / Frappe v16

Multi-session WhatsApp (linked-device / QR) integration:

* **WhatsApp Hub page** (`/app/whatsapp-hub`) – link accounts by scanning a QR code, status cards, log out, sync groups, test send.
* **WhatsApp Settings** (single) – master enable/disable switch, gateway URL + secret, defaults, log retention.
* **WhatsApp Account** – one per linked phone (session). Default account, enable/disable per account.
* **WhatsApp Group** – synced from the phone; link a group to a Customer / Supplier / Employee.
* **WhatsApp Message Log** – every message, status Queued → Sent → Delivered → Read, retry on failure.
* **Notification channel "WhatsApp"** – the standard Notification doctype (events, conditions, Jinja, recipients by field/role,
  attach print PDF) plus: account, fixed group, "send to party's number", "send to party's linked groups".
* **Send → WhatsApp** button on every saved document (numbers resolved from Customer/Supplier/Contact/Employee).

## Architecture

Frappe cannot hold a WhatsApp Web session, so a small Node gateway (`gateway/server.js`, built on Baileys) keeps one
linked-device session per account. The gateway posts QR codes, status changes, delivery receipts and incoming messages to
Frappe (`/api/method/whatsapp_hub.api.webhook`); Frappe sends messages to the gateway over REST. Both directions are
authenticated with the shared `API_SECRET`.

## Install

```bash
# 1. Frappe app
cd ~/frappe-bench
bench get-app --branch version-16 https://github.com/ggraza/whatsapp_hub.git
bench --site yoursite install-app whatsapp_hub
bench --site yoursite migrate && bench build --app whatsapp_hub
bench restart

# 2. Node >= 20 and PM2 (skip what is already installed)
node -v
pm2 --version || sudo npm install -g pm2

# 3. Gateway
cd ~/frappe-bench/apps/whatsapp_hub/gateway
npm install

# generate a secret once; use the SAME value in WhatsApp Settings -> API Secret
openssl rand -hex 32

export API_SECRET=<paste-the-generated-secret>
PORT=3100 HOST=127.0.0.1 pm2 start server.js --name wa-gateway
pm2 save
pm2 startup      # run the sudo command it prints, so the gateway starts on boot
```

> **Never commit the API secret** (not in this README, not in scripts). Anyone who has it can send messages
> from your linked numbers. If it was ever committed or shared, generate a new one, update WhatsApp Settings,
> and restart the gateway with `API_SECRET=<new> pm2 restart wa-gateway --update-env`.

Then in ERPNext:

4. Open **WhatsApp Settings**: Gateway URL `http://127.0.0.1:3100`, the same API Secret, tick *Enabled*, save, click *Test Gateway*.
5. Open **WhatsApp Hub** → *Link New Account* → scan the QR (Phone → Settings → Linked devices → Link a device).
6. Notification → Channel = **WhatsApp**.

## Day-to-day gateway commands

```bash
pm2 status
pm2 logs wa-gateway --lines 80
pm2 restart wa-gateway
pm2 stop wa-gateway
pm2 start wa-gateway
```

Without PM2 (foreground test, more logging):

```bash
cd ~/frappe-bench/apps/whatsapp_hub/gateway
LOG_LEVEL=info API_SECRET=<secret> node server.js #jcdYfJTxlDUkIm7UBo1Ulka/egR4GUQBU4MSlwDeLfk=
curl -H "x-api-secret: <secret>" http://127.0.0.1:3100/health    # {"ok":true,"sessions":0}
```

## Troubleshooting: recipient sees "Waiting for this message. This may take a while. Learn more."

This means the message reached the recipient but could not be decrypted. ERPNext and the gateway are working;
the cause is the WhatsApp encryption layer. Check, in this order:

1. **Baileys version.** Use the 7.x line. Old 6.x releases (including `^6.7.x`) break when WhatsApp changes
   how accounts are addressed, which produces exactly this symptom.
   ```bash
   cd ~/frappe-bench/apps/whatsapp_hub/gateway
   npm view @whiskeysockets/baileys dist-tags      # shows latest / rc / legacy tags
   npm install @whiskeysockets/baileys@latest
   ```
   Keep `package.json` pinned to the exact tested version (no `^`), currently `7.0.0-rc14`,
   so a later `npm install` does not silently change it.
2. **`getMessage` handler.** `server.js` must pass `getMessage: async (key) => sentCache.get(key.id)` to `makeWASocket`
   and store every sent message in `sentCache`. This lets the library resend a message when the recipient's phone
   requests a retry. Do not remove it.
3. **Clean relink after any Baileys upgrade.** Old credentials are not reliable across versions.
   ```bash
   pm2 stop wa-gateway
   rm -rf ~/frappe-bench/apps/whatsapp_hub/gateway/sessions/*
   ```
   On the phone remove the old entry under Linked devices, then start the gateway
   (`pm2 start wa-gateway`) and scan a fresh QR from the WhatsApp Hub page.
4. **Test with a different number.** Messages sent to the same number the account is linked to often show
   "Waiting for this message" regardless of library version. The first message to a new contact can also take a
   few seconds; wait a minute before judging.
5. Still failing: `LOG_LEVEL=info`, send a test, and look in `pm2 logs wa-gateway` for `Bad MAC`, `No session` or `retry` lines.

## Operations & security

* Keep the gateway on `127.0.0.1` or a private network; put it behind TLS if it is remote. The secret is checked in both directions.
* Back up `gateway/sessions/` (it contains WhatsApp credentials) and treat it as a secret. Add `gateway/sessions/` and `gateway/node_modules/` to `.gitignore`.
* The gateway must be able to reach the site URL for webhooks (set *Site URL for Webhooks* if you are behind a proxy).
* Sends are queued (RQ `short`) and paced per session with a random 1.5–4 s delay.
* Local phone numbers starting with 0 get the *Default Country Code* prepended.
* Upgrading Baileys: change the version, `npm install`, then do the clean relink above.

## Important

This uses the unofficial WhatsApp Web protocol (Baileys). Bulk or unsolicited messaging can get numbers banned and may
conflict with WhatsApp's Terms. Use it for transactional messages (invoices, delivery notes, reminders). For
high-volume marketing use the official WhatsApp Business Cloud API; `utils.deliver()` is the single place to swap the transport.
