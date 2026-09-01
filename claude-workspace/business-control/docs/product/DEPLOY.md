# Going public: deploying Business Control to the internet

Everything customer-facing (affiliate links, promo QRs, the install pipeline, support chat) needs a real URL before customers outside your wifi can use it.
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
by itself. 
Real HTTPS also unlocks phone camera/mic (calls, scanner) and iOS
push with no warnings.

One domain serves all three surfaces: `shop.yourbrand.com/` is the customer
storefront (crawlable — `robots.txt` + `sitemap.xml` are served there),
`/ops/` is the team's ERP app, `/admin` is the store admin. 
If you'd rather keep operations off the public host entirely, add a second site block (e.g. `ops.yourbrand.com`) that proxies the same port and block `/ops*` on the shop host.

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

**The one cron.** Nightly backups pull from every worker node, so the
whole fleet lands in one archive on the provider and a worker needs no
cron of its own. One line on the provider box:

```
17 2 * * * cd /opt/business-control && .venv/bin/python scripts/backup.py >> data/backups/backup.log 2>&1
```

The script exits non-zero when any tenant could not be pulled (cron mails
you), writes `data/backups/last.json`, and the Platform tab reads it — a
green "backed up 3h ago" chip when the promise is being kept, a red one
when it is not.

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

Copy `data/backups/` off the server periodically (rsync/rclone) — a backup on the same disk only survives small mistakes.

## 7. After go-live

- Sign in as founder/owner with the new admin key **and set your password immediately** (the same password field at login adopts it).
- Re-print shelf/packaging QRs — they now encode the public URL.
- The LAN start commands still work on your Mac for a local copy; keep the production `data/` and your local `data/` mentally separate (backups tell you which is which).

## The fleet, publicly: a website from a form

With one public box configured this way, standing up a client IS handing
them a website: fill the stand-up form, and they answer at
`<tenant>.clients.yourbrand.com` with TLS, a shaped storefront and their
name on it — before the call ends.

**One-time setup, three pieces:**

1. **Wildcard DNS.** One record: `*.clients.yourbrand.com → <your VPS IP>`.
   Every future tenant is covered by it; standing one up never touches DNS
   again.

2. **The public suffix**, in the provider tenant's `config.json`:

   ```json
   "fleet": {"public_suffix": "clients.yourbrand.com"}
   ```

   From then on every stand-up also registers
   `<tenant>.clients.yourbrand.com` and sets that tenant's
   `public_base_url`, so QR codes, sign-in links and Stripe returns carry
   the public name from birth. The stand-up modal shows the address before
   you click, and the toast hands it to you after.

3. **Caddy with on-demand TLS**, gated by the registry:

   ```
   {
     on_demand_tls {
       ask http://127.0.0.1:8860/caddy/ask
     }
   }

   *.clients.yourbrand.com {
     tls {
       on_demand
     }
     reverse_proxy 127.0.0.1:8860
   }
   ```

   `/caddy/ask` answers 200 only for hostnames the tenant registry
   actually claims (suspended tenants included — their 503 page deserves
   TLS too), and 404 for everything else. Without the gate, on-demand TLS
   would mint a certificate for any hostname a stranger pointed at your
   box.

**A client's own domain later** (`shop.theirbrand.com`) is the launch
flow: point their DNS at the box, click Launch on their engagement, and
`/caddy/ask` starts saying yes to the new name because the registry does.

**Run it as a service** so it survives reboots (`systemd`):

```ini
# /etc/systemd/system/business-control.service
[Unit]
Description=Business Control
After=network.target

[Service]
WorkingDirectory=/opt/business-control
ExecStart=/opt/business-control/.venv/bin/python scripts/launch.py --port 8860
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl enable --now business-control
```

One 4 GB box carries 25 units — by the book's own arithmetic, that is a
real client roster before a second machine earns its keep. When it does:

## The second machine: a node in three steps

1. **Book it.** Platform tab → add a node with its **address**
   (`http://10.0.0.2:8860` on a private network, or an https:// name).
   Booking with an address mints the node's key.

2. **Join it.** The node's **Join cmd** button prints one command — run
   it on the fresh Ubuntu/Debian box as root:

   ```sh
   curl -fsSL https://shop.yourbrand.com/fleet/install.sh -o /tmp/bc-install.sh \
     && sudo bash /tmp/bc-install.sh --node node-b --key <minted-key> \
          --provider https://shop.yourbrand.com
   ```

   It fetches the app bundle from the provider (authenticated by the
   node key), stands it up under systemd with the node's identity in its
   environment, and proves the node answers before claiming success.
   Firewall the box so only the provider (and port 22) reaches it.

3. **Use it.** **Check** pings it (alive, code version, tenants);
   stand-ups and **Move** ship tenants to it; the nightly backup pulls
   from it; **Update** pushes the provider's current code — the worker
   applies the bundle, exits, systemd restarts it, and the provider
   polls until the ping answers with the pushed version. Success is
   observed, not assumed. Requests for its tenants that still arrive at
   the provider (wildcard DNS at the front box) are proxied through;
   pointing a tenant's DNS at its node directly is the optimization,
   not a prerequisite.

`fleet.provision_cmd` remains the optional hook that makes step 1 also
CREATE the VM at your cloud provider; without it, booking is a record
and the machine is yours to rent.
