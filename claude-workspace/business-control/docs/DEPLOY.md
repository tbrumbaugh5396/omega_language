# Going public: deploying Business Control to the internet

Everything customer-facing (affiliate links, promo QRs, the install pipeline,
support chat) needs a real URL before customers outside your wifi can use it.
This is the half-day checklist.

## 1. Get a server and a domain

- Any small VPS works (Hetzner/DigitalOcean/Lightsail, 1–2 GB RAM is plenty).
- Point a DNS A record at it, e.g. `shop.yourbrand.com`.

## 2. Install the app on the server

```sh
# on the VPS (Ubuntu/Debian)
sudo apt install -y python3 python3-venv
# copy business-control.zip up, then:
unzip business-control.zip && cd business-control
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python3 scripts/make_icons.py
# note the admin key it prints:
./.venv/bin/python3 -c "import sys; sys.path.insert(0,'src'); from backend import db, config; db.init(); print(config.load()['admin_key'])"
```

Do **not** run seed.py on the production server — start clean.

## 3. Reverse proxy with automatic HTTPS (Caddy)

```sh
sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
shop.yourbrand.com {
    reverse_proxy 127.0.0.1:8860
}
```

`sudo systemctl reload caddy` — Caddy fetches and renews the TLS certificate
by itself. Real HTTPS also unlocks phone camera/mic (calls, scanner) and iOS
push with no warnings.

One domain serves all three surfaces: `shop.yourbrand.com/` is the customer
storefront (crawlable — `robots.txt` + `sitemap.xml` are served there),
`/ops/` is the team's ERP app, `/admin` is the store admin. If you'd rather
keep operations off the public host entirely, add a second site block (e.g.
`ops.yourbrand.com`) that proxies the same port and block `/ops*` on the shop
host.

## 4. Run the app as a service

`/etc/systemd/system/business-control.service`:

```
[Unit]
Description=Business Control
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/business-control
ExecStart=/opt/business-control/.venv/bin/python3 scripts/launch.py --host 127.0.0.1
Restart=always

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl enable --now business-control
```

Binding to 127.0.0.1 means only Caddy (with TLS) can reach it.

## 5. Harden the app config (`data/config.json`)

| key | set to | why |
|---|---|---|
| `public_base_url` | `https://shop.yourbrand.com` | QRs, sign-in links, emails, and Stripe return URLs use it instead of the LAN IP |
| `require_passwords` | `true` | name-only sign-in is fine on a trusted LAN, not on the internet. Existing accounts adopt a password on their next sign-in; new accounts must set one |
| `admin_key` | (rotate it) | anyone who ever saw the old one can mint admins |
| `smtp` / `stripe_secret_key` | your real creds | entered on the server, never committed anywhere |

Firewall: allow only 22/80/443 (`ufw allow 22,80,443/tcp && ufw enable`).

## 6. Backups on a schedule

```sh
crontab -e
# nightly at 3:15, keep 30 days (backup.py rotates automatically)
15 3 * * * cd /opt/business-control && ./.venv/bin/python3 scripts/backup.py
```

Copy `data/backups/` off the server periodically (rsync/rclone) — a backup on
the same disk only survives small mistakes.

## 7. After go-live

- Sign in as founder/owner with the new admin key **and set your password
  immediately** (the same password field at login adopts it).
- Re-print shelf/packaging QRs — they now encode the public URL.
- The LAN start commands still work on your Mac for a local copy; keep the
  production `data/` and your local `data/` mentally separate (backups tell
  you which is which).
