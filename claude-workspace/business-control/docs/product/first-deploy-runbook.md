# First real deploy — the runbook

DEPLOY.md explains the *why*; this is the afternoon's *checklist*. Every
step ends with a command that PROVES it worked, because the point of the
first real deploy is to shake out what only a real Linux box can — the
installers, systemd, Caddy, the hardening defaults. Expect small
off-by-ones in the install scripts: they are syntax-checked and
literal-tested but have never run under real systemd. Note anything that
needed fixing; each is a one-line patch waiting to be made.

**You need:** a $5 Ubuntu/Debian VPS, a domain, ~2 hours.

## 1. The box

```sh
ssh root@<vps>
apt-get update -y && apt-get install -y python3 python3-venv unzip curl caddy ufw
ufw allow 22,80,443/tcp && ufw enable
```

Point DNS: `shop.<yourdomain>` A-record → the VPS IP, plus a wildcard
`*.clients.<yourdomain>` → same IP (for tenant stand-ups later).

## 2. The app

```sh
mkdir -p /opt/business-control && cd /opt/business-control
# copy the tree up (from your machine):
#   rsync -a --exclude .venv --exclude data --exclude __pycache__ \
#     claude-workspace/business-control/ root@<vps>:/opt/business-control/
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

**Prove it:** `PYTHONPATH=src ./.venv/bin/python tests/test_smoke.py`
— the whole suite, on the real box. If 1,891 checks pass here, the code
itself is not what the rest of the afternoon finds.

## 3. Service + proxy

Follow DEPLOY.md §3–4 verbatim (Caddyfile, systemd unit, enable). Then:

```sh
systemctl status business-control --no-pager | head -3   # active (running)
curl -s -o /dev/null -w '%{http_code}\n' https://shop.<yourdomain>/   # 200, real TLS
```

## 4. Harden — and PROVE the hardening

Set `public_base_url` in `data/config.json`, restart, then run each
assertion; every one is a behavior this session built and the suite
promises:

```sh
B=https://shop.<yourdomain>
# passwords now required (exposure decided it):
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"name":"Probe","mode":"create"}' $B/api/login   # → password required
# the bare API no longer mints:
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"name":"Stranger"}' $B/api/login                # → 404 no account
# the PWA answers (or 404s if you sell it separately):
curl -s -o /dev/null -w '%{http_code}\n' $B/store.webmanifest
# the machine door:
#   ops → Integrations → mint a read key, then:
curl -s -H "Authorization: Bearer bck_..." $B/api/orders   # 200
curl -s -X POST -H "Authorization: Bearer bck_..." \
  $B/api/admin/branding                                # → 403 read-only
```

Sign in as founder with the printed admin key, **set your password**,
rotate the key (DEPLOY.md §5), add the backup cron (§6). Prove the cron:
run `scripts/backup.py` once by hand and check the Platform tab's chip.

## 5. Node services — the installers' first real run

```sh
bash scripts/install_translate.sh --langs en,es
curl -s http://127.0.0.1:5000/languages | head -c 60      # JSON, not refusal
```

Then in ops: the Platform tab's local card wears a green `translate`
pill, and `/api/learn/voice/providers` on a tenant says `node service`.
Repeat for the SFU when a class needs it:
`bash scripts/install_sfu.sh --host shop.<yourdomain>` — prove with a
two-browser class join, then close the class and watch the tape land in
the session's recordings.

## 6. The second machine (optional, +30 min)

Book a node in the Platform tab with the second box's address, copy
**Join cmd**, paste it there. Prove: **Check** shows `up · code <hash>
(current)`; stand a test tenant up ON the node; `scripts/backup.py`
pulls it; **Update** after any local commit shows the new hash. This
exercises the entire fleet story end to end.

## 7. Report back

The gap between "works in the suite" and "works on Ubuntu under
systemd" is exactly what this afternoon measures. Whatever needed
touching — a package name, a unit line, a path — goes back into the
install scripts, so the second deploy is nothing but pasting.
