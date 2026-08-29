# Multi-tenancy — one process, tenant-per-database

**Written August 2026.** Implements §1 of [saas-scaling.md](saas-scaling.md):
work items 1 (router + registry), 2 (per-tenant connect/config, namespaced
hub and push) and 5 (per-tenant backups) are shipped. Items 3 (on-demand
TLS) is a Caddy config documented below; item 4 (Stripe billing on a
control plane) is not built.

## How it works

The host header picks the tenant. A middleware resolves it before anything
touches a database, a contextvar carries it through the request — including
into daemon threads that outlive it — and every piece of state a business
owns lives under its own directory:

```
data/
  tenants.json                 the registry: who answers to which hostname
  tenants/
    studio/                    business_control.db · config.json ·
    zenjoy/                    uploads/ · vapid_private.pem · exports/
```

**Tenancy is off until `data/tenants.json` exists.** Without it, the bare
`data/` directory is the sole tenant and nothing behaves differently —
which is why a single-shop install never meets this machinery, and why the
whole legacy test suite runs unchanged.

What is shared across tenants, on purpose: the code, the frontend assets,
the client kit (`docs/business-control-b2b-client/`), and the quote bench.
What is never shared: databases, config (each tenant mints its own
`admin_key` and `pin_pepper`), uploads and documents, VAPID push keys, the
chat hub (keyed by tenant + user), and the rate limiters.

## The registry

```json
{
  "default": "studio",
  "tenants": {
    "studio": {"hosts": ["localhost", "127.0.0.1"]},
    "zenjoy": {"hosts": ["zenjoy.localhost"]}
  }
}
```

Resolution order: exact host alias → `<id>.localhost` / `<id>.local`
convention → the default, for local-looking names only (bare IPs,
`localhost`, `testserver`). **An unclaimed public hostname is a 404**,
never a fall-through — a typo'd DNS record must not show one business's
data under another's name.

Browsers resolve `*.localhost` to the loopback on their own, so
`zenjoy.localhost:8860` works locally with no `/etc/hosts` entry.

## Operating it

- **Add a tenant:** from a Python shell,
  `from erp.backend import tenancy; tenancy.create("acme", hosts=["acme.localhost"])`
  — directory, config with fresh secrets, registry row, schema, all in one
  call. Or edit `tenants.json` and restart.
- **Seed a tenant:** `python scripts/seed_zenjoy.py --tenant zenjoy` — the
  seeders take `--tenant` and aim every write at that tenant's database.
- **Back up:** `scripts/backup.py` archives every tenant directory (DB
  snapshot, config, VAPID key, and uploads) plus the registry, in one
  tar.gz. Restore sets the whole tenants tree aside before extracting.
- **The split:** `scripts/split_tenants.py` is the one-shot that took the
  original single install apart — zenjoy kept the shop, studio inherited
  the client pipeline and the operators. It refuses to run twice; the
  un-split database stays behind as `business_control.pre-split.db`.

## Push notifications after the split

Each tenant has its own VAPID key pair (browsers bind a subscription to
the server key — a shared pair would make every tenant one business to the
push service). Consequence: **devices subscribed before the split must
re-subscribe** from the bell panel. One-time cost, said out loud here.

## Public deployment

Caddy, with a host per tenant — automatic TLS per name:

```
studio.example.com, zenjoy.example.com {
    reverse_proxy 127.0.0.1:8860
}
```

For customer domains at fleet scale, Caddy's
[on-demand TLS](https://caddyserver.com/docs/automatic-https#on-demand-tls)
issues certificates at handshake time for any hostname the registry
answers — pair it with an `ask` endpoint that checks `tenants.json`.
Set each tenant's `public_base_url` in its own `config.json` so QR codes,
sign-in links and Stripe returns carry the right domain.

## The fleet, and Lingua

The workspace `launch.json` carries the whole fleet: this process (all
business-control tenants on :8860) and **lingua-portal**, which is its own
codebase — stdlib Python, its own auth, its own working per-tenant control
plane — running on :8800 (portal) and :8700 (marketing site).

**Lingua is managed as a client of the studio tenant today** (the
engagement, quotes, documents and portal machinery), with the port into
business-control as the stated goal: making the priced-but-unbuilt
Learning capability real. When that build starts, the cheapest integration
seam on the lingua side is `services/tenants.py:record_subscription` (the
payment-adapter hook) and `services/license.py:set_license` (the
platform-side write the portal reads) — the two places its control plane
already expects an outside biller.
