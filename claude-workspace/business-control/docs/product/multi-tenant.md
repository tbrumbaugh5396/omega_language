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

**Nor is the voice.** The theme (colours, all three typefaces, the stand-in
product art), the interface's own words (`store_meta.ui_strings`) and the
"ways to work with us" landing pages (`store_meta.partner_pages`) are each
the tenant's data, with the shipped value as a neutral default. See
[studio-storefront.md](studio-storefront.md) for what moved out of the
codebase and why.

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

## The client's window — both sides see their documents

The registry can declare one tenant the **provider** (`"provider":
"studio"`): the business whose pipeline manages the others. That closes the
loop in both directions:

- **The studio sees every client** — the Clients board, engagements,
  documents, quotes and portals, exactly as before.
- **A client tenant sees its own paperwork** — its Documents tab carries a
  "From <studio>" card reading straight from the provider's pipeline: the
  stage, gates closed, every to-client document (view + PDF), and the
  roadmap link. No second login; read-only; signing stays on the roadmap,
  where the audit trail lives.

The link is the engagement's `tenant_id`, falling back to the slug — which
is how zenjoy finds zenjoy with no configuration. The wall holds by
construction: the cross-tenant read runs inside `tenancy.run_as(provider)`
for exactly the width of the handler, and every query carries the same
`side='to_client'` clause the portal lives by. An internal document is not
withheld from the client tenant — it is unreachable.

## The fleet: nodes, and who lives on which one

`Platform` in the studio's ops app (provider tenants only — the tab does
not exist elsewhere, and neither does its API). A **node** is a machine
running this codebase; a **tenant** is a business whose data lives on
exactly one node.

Capacity is counted in **units**, not tenants — a corner shop and a
fifty-location distributor are not the same load:

| Class | Units | Fits |
|---|---|---|
| micro | 1 | 1 location · ≤5 seats |
| growing | 4 | ≤3 locations · ≤20 seats |
| large | 16 | ≤10 locations · ≤75 seats |
| dedicated | the node | a node to itself |

A 4 GB node carries **25 units**. Standing a client up asks where they go:
an existing node with room, or a new node spun up in the same act. Left to
choose, placement takes the *fullest* node that still fits — bin-packing,
because the bill is per node, not per unit.

**A node nobody is left on is destroyed.** Automatically, on the tenant's
way out (removal or a move), and reported in the toast that confirms it.
Paying for an empty VPS is the most common way a fleet's margin leaks, and
the minute it empties is the only minute anyone would think to look. Two
nodes are never auto-destroyed: `local` (this machine cannot be handed back
from inside itself) and any node still carrying a tenant.

Leaving has two settings. **Suspend** is reversible: the hostname answers
**503**, not 404 — the site exists and is paused, and telling a paused
customer "no such site" is a lie — and not one byte of their data is
touched. **Remove** takes them off the fleet; their directory moves to
`data/retired/<id>-<stamp>` unless the operator unticks it, because a
business that leaves still owns its records and the week after a
cancellation is exactly when someone asks for an export.

Provisioning is a driver, configured per provider tenant:

```json
"fleet": {"provider": "hetzner",
          "provision_cmd": "hcloud server create --name {node} --type {size} --location {region} --image docker-ce",
          "destroy_cmd": "hcloud server delete {node}"}
```

Unset, a node is a booking in the registry — honest bookkeeping for a fleet
provisioned by hand, and the button still works. Set, the button really
makes a server, and a command that fails fails the request: a node the
operator believes exists, that doesn't, is worse than an error.

Every provision, placement, move, suspension and reap is written to
`fleet_events` in the **provider's own** database and shown as Fleet
history, so "when did that node go, and who took it" has an answer.

**The quote sizes the install.** A quote's bench state carries the
locations, seats and capabilities being bought — the same numbers the
fleet's classes are defined by. Closing the **contract gate** on an
engagement with no install offers the stand-up on the spot, pre-sized from
the **signed** quote (a bigger unsigned draft filed afterwards does not
win — the offer the client accepted governs), with the derivation shown:
"2 locations, 12 seats → growing". Offered, not performed: infrastructure
appears when an operator clicks, and the offer disappears the moment the
tenant exists. From one signature, the click-path is: contract signed →
stand-up offered at the sold size → tenant live on its hostname, named on
its storefront, hosting schedule filed in the binder.

**And the quote shapes the home page.** The same capability set picks a
starter layout (`storefront/backend/layouts.py`): a **shape** gives the
skeleton — commerce, courses, nonprofit, or services — and capabilities the
shape doesn't lead with still earn their sections, so a teaching nonprofit
gets the courses page with the support banner composed in. Priority is
deliberate: what a business *makes* beats how it takes money (learning >
fundraising > selling > services). Each shape also ships its **secondary pages** — where "tell them more"
lives: a shop gets its story and a delivery-and-returns page, a school
gets the instructor and the curriculum, a nonprofit gets the mission and
an impact page (which the hero's "See the work" links), a practice gets
who-we-are and how-an-engagement-runs. The nav is rebuilt to carry them,
keeps Reviews only where the home actually has a reviews section to
anchor, and names the pages that *exist* under their stored titles — a
re-run neither overwrites a page an operator has touched nor drops its
link. The nav's first word follows the shape.
Every section is built on the schema's own defaults, and the scaffolding
never invents a fact — no customer counts, no shipping policy nobody set.
Applied once, at stand-up, onto a page nobody has touched; without a
quote, the shipped default stays.

**And the act writes its own paper.** Standing a client up under their
engagement files the **hosting & infrastructure schedule**
(`04-agreement/contracts/hosting-and-infrastructure.md`) into their binder,
pre-filled with the tenant id, hostnames and size class that were actually
stood up — the grant to provision and operate, data ownership and export,
what suspension means (503, reversible, data untouched), and the exit terms
(90-day retention, then confirmed deletion). The other contracts assume the
client owns their hosting; this schedule is for the opposite arrangement,
and it exists so the authority to run a business on the platform is a
signed page, not an understanding. A re-stand-up after a move does not file
it twice.

## The design library — design once, place everywhere

Provider-only, in the theme editor. Select a section on the studio's own
storefront and **Save to library** (same name updates the entry); the
library then offers **insert on this page** and **push to clients** — a
tenant chooser drawn from the fleet board, the provider itself excluded.

The rule that keeps the wall honest: **a push adds a section, stamped
with the design it came from, and from that moment the placement belongs
to the tenant** — movable, editable, deletable in their own editor. A
later push adds another copy rather than reaching back into anyone's
page; deleting a design from the library leaves every placement
standing. The stamp (`page_sections.design_id`) is provenance, not a
grip: it lets the library report where each design lives, counted across
the fleet, so reach is visible before anyone pushes again. Every push
lands in the fleet history with who, what and where.

Pushed copy is scaffolding under the same contract as the starter
layouts — a starting point the receiving tenant edits, not the studio's
voice compiled into their shop. A tenant without the target page is
skipped and said so, never silently given a page they never made.

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

**Lingua now runs as its own tenant** — `lingua.localhost`, on the local
node at 4 units, with its own database, config, secrets and uploads,
stood up through Platform → Stand up a client rather than by hand. The
studio's engagement for it carries `tenant_id = 'lingua'`, so Lingua's own
Documents tab reads the studio's paperwork for Lingua across the wall.

The lingua-portal codebase is still separate and still runs on :8800 and
:8700 — the tenant is its business side (ops, CRM, storefront), not a port
of the product. That port is still the stated goal: making the priced-but-unbuilt
Learning capability real. When that build starts, the cheapest integration
seam on the lingua side is `services/tenants.py:record_subscription` (the
payment-adapter hook) and `services/license.py:set_license` (the
platform-side write the portal reads) — the two places its control plane
already expects an outside biller.
