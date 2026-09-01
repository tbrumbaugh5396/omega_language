# Product documentation

How Business Control itself works, what it costs to run, and the architecture decisions behind it.

This is the **product's** documentation. 
The client-facing side of the business: 
 
- consultations, proposals, contracts, delivery 
- lives in [`docs/business-control-b2b-client/`](../business-control-b2b-client/README.md).

---

## Run it

Kept current with the code. If one of these is wrong, it's a bug.

| Document | What it answers |
|---|---|
| [DEPLOY.md](DEPLOY.md) | Getting an install onto the internet: VPS, Caddy with automatic TLS, systemd, config hardening, backups on a schedule |
| [USERS.md](USERS.md) | Who can sign in, what each role sees, the tab access matrix, and the security model to read **before** going multi-user |
| [studio-storefront.md](studio-storefront.md) | Business Control's own shop — seeded from the price book, and the branding that had to leave the codebase for it to exist |
| [multi-tenant.md](multi-tenant.md) | Running several businesses from one process — the host-header router, the tenant registry, what is shared vs owned, and the split that separated the studio from ZenJoy, and the fleet of nodes clients are placed on |
| [learning.md](learning.md) | The Learning capability — the lingua-portal port: which layer landed on which surface, the two pure modules that moved verbatim, checkout-as-admissions, and the seven follow-on areas now landed (recordings, library, voice, QR identity, data rights, calendar, SFU) |
| [nutrition.md](nutrition.md) | The Nutrition capability — the macro-kitchen port: pure calorie math, tenant food library, coach caseload, checkout-as-coaching-desk |
| [node-services.md](node-services.md) | Node services — daemons installed once per machine and shared by every tenant on it: the manifest, the tenant-wins/node-floor/graceful-absence resolution rule, and the LibreTranslate installer that proves the pattern |

> `DEPLOY.md` is the technical runbook the studio's [delivery
> roadmap](../business-control-b2b-client/roadmap.md) points at rather than
> copies. Change deployment here, not there — a second copy of these steps is a
> copy that goes stale silently, and it goes stale on the day it matters most.

## Decide it

Records of decisions taken at a point in time. **Written August 2026**, and
several carry prices that move.

| Document | The decision |
|---|---|
| [ecommerce-architecture-decision.md](ecommerce-architecture-decision.md) | Shopify vs. custom — resolved by splitting the question. Own the back office, rent the money edge. Recommendation: **headless Shopify** with the ERP as system of record |
| [private-subscription-app.md](private-subscription-app.md) | Build subscription billing or rent Recharge/Loop. Decision: **prototype the private-app route first**, rent only if our dunning measurably underperforms at real volume |
| [saas-scaling.md](saas-scaling.md) | What it takes to sell this as SaaS — tenant-per-database, per-feature hosting costs, and what those do to margins |

## Price it

| Document | What it answers |
|---|---|
| [price-book.md](price-book.md) | Every capability, what it depends on, what it costs us and what we quote — with the bundles, tiers, meters and services, and a list of every place the sources contradict each other |
| [quote-bench.html](quote-bench.html) | The working quoter: pick capabilities, dependencies wire themselves, and the bill assembles live — studio view with costs and margins, client view without. Served inside the ERP behind admin auth (a client's page → Quote), where "File to client" saves the quote as a paper on that client |

> The price book was lifted out of the deck, which held three separate data
> models that had already drifted apart. Until §8 of it is settled, **the deck
> and the price book will drift too** — the deck still carries its own copies.

> **Don't silently update a decision document.** It records what was decided,
> by whom, and on what evidence — which is the whole reason to keep one. When
> the decision changes, write the new one and mark the old superseded. A
> decision doc quietly edited to match today's plan can no longer tell you why
> you're where you are.
>
> Anything marked *(verify)* was time-sensitive when written. Check the vendor
> before modelling revenue on it.

### The three questions that decide whether the architecture holds 

From [§8 of the architecture
decision](ecommerce-architecture-decision.md#8-decisions-still-open), unresolved and load-bearing:

1. **Are boxes fixed-contents or curated per subscriber?** Fixed means very little to build. Personalised means an allocation engine, and the build-vs-buy line moves.
2. **Who owns inventory truth — ERP or Shopify?** Wanting Shopify to own it is a signal the ERP is further from done than it looks.
3. **Who owns the customer record?** Pick a winner up front, or spend a year reconciling duplicate customers by email.

## Build it

| Document | What it tracks |
|---|---|
| [engagements-plan.md](engagements-plan.md) | Running the B2B client kit from the ERP — client records, document generation, signatures, folder export (shipped); gates, portal, rhythm (planned) |

## Present it

| Document | For |
|---|---|
| [ecommerce-stack-deck.html](ecommerce-stack-deck.html) | The 39-slide walkthrough of the stack decision. Open it in a browser; it's self-contained |

Its sources are the three decision documents above. 
If you change one of them, the deck is now wrong — it doesn't read from them.

---

## What isn't here

| Looking for | It's in |
|---|---|
| How to sell, scope, quote or hand over a project | [`business-control-b2b-client/`](../business-control-b2b-client/README.md) |
| Running it locally, the module inventory, the API | the [top-level README](../../README.md) |
