# Price book — v2

**Written August 2026. Supersedes the August 2026 edition (`price-book.md`),
which is now historical.** Do not edit the old one to match this; it records
what was priced before and why the change was made.

Every capability, what it depends on, what it costs us, what we quote, and a
list of what is still contradictory. Prices marked *(verify)* were
time-sensitive when written.

> **This document is the source.** The deck and the quote bench both carry
> copies of these numbers and neither reads from here. When you change a price,
> change it here first, then push it to the other two — and expect to find
> they had drifted anyway.

---

## 0. What changed from v1, and why

| Change | Was | Now | Closes |
|---|---|---|---|
| Capability pricing | 18 individual prices, $9–$35 | Three bands: **$20 / $30 / $50** | §8 #15 (three data models) largely dissolves — one rule, not nineteen numbers |
| Unpriced capabilities | 9 with no price, unsellable | All 9 banded | §8 #5 |
| Platform Core | $49 | **$50** | Round arithmetic |
| Packaged tiers | $49 / $149 / $399 | **$200 / $400 / $700** | Tiers undercut every bundle; the menu was pointless — and a tier is a round number, not a number pretending to be smaller |
| Tier contents | "roughly Commerce Core + Workforce" | Explicit capability sets (§6) | The "quote the cheaper one" rule was uncomputable |
| Care plan | Sold, but outside the price book | **Part 2 of the monthly bill** (§12) | The bill was one number for two different businesses |
| White-labelling | Not offered | Four levels, $0–$200/mo (§8) | New revenue, zero cost to serve |
| Build pricing | One figure | Optionally split by surface (§12) | Scope arguments |
| Scale metric | None | Optional subscriber band (§7) | Revenue did not grow with the client |

**Why bands.** Marginal cost to serve a capability is zero, so per-capability
prices were never cost-derived — they were nineteen independent guesses, each
duplicated in three places, each free to drift. Three bands are one decision
applied twenty-seven times. The mean capability price moves from $21.44 to
$30.00, so this is a repricing as well as a simplification. **Grandfather
existing clients or say plainly that you are raising prices.** Do not pretend
it is only tidying.

**What this does not fix.** The volume discount still inverts at ten boxes.
See §15 item 1 — it is one number and it is still wrong.

---

## 1. The pricing rule

```
monthly bill = PART 1 (platform) + PART 2 (support & maintenance)

PART 1 = (Σ capability bands × volume discount)
       + Platform Core
       + seat & location overage
       + metered overage
       + white-label licence
       + scale band, if enabled
       → then nonprofit, then annual

PART 2 = care plan + content-change overflow      (no discounts apply)

Sold separately, cancelled separately: Studio, growth retainer
One-time: build, white-label setup
```

Order matters and it is not the order anyone guesses. Discounts apply to Part
1 only. Services are labour, and discounting labour is discounting your own
time.

---

## 2. The bands

| Band | Price | What belongs here |
|---|---|---|
| **Light** | **$20** | Supporting capabilities — one job, configured once, low ongoing surface |
| **Standard** | **$30** | The default. A working area of the business with its own screens and data |
| **Heavy** | **$50** | Capabilities that are a product in their own right, and would be bought standalone elsewhere |

A new capability gets a band, not a price. If it needs a fourth band, the
answer is usually that it is two capabilities.

---

## 3. Capabilities

Dependencies are hard: selecting a capability selects everything it rests on.
An asterisk marks the nine that had no price in v1.

| Capability | Band | Price | Requires |
|---|---|---|---|

| **Operations** | | | |
| Sourcing | Light | **$20** | Core |
| Inventory | Standard | **$30** | Core |
| Production | Standard | **$30** | Inventory |
| Warehouse | Light | **$20** | Inventory |
| Distribution | Heavy | **$50** | Inventory |
| Learning | Heavy | **$50** | Core |
| Voice & translation * | Standard | **$30** | Learning |
| Nutrition | Standard | **$30** | Core |

| **Revenue ops** | | | |
| Selling | Heavy | **$50** | Core |
| Subscriptions & boxes | Standard | **$30** | Selling + Payments |
| Fundraising | Standard | **$30** | Payments |
| Marketing | Standard | **$30** | Core |
| CRM & Support | Standard | **$30** | Comms |
| Events | Light | **$20** | Workforce |
| Affiliates | Light | **$20** | Core |

| **Finance** | | | |
| Payments | Light | **$20** | Core |
| Accounting * | Standard | **$30** | Core |
| Finance * | Standard | **$30** | Payments + Accounting |
| Treasury & investments * | Standard | **$30** | Finance |

| **People & management** | | | |
| Workforce | Standard | **$30** | Core |
| Onboarding * | Light | **$20** | Workforce |
| Payroll * | Standard | **$30** | Workforce |
| Intelligence | Heavy | **$50** | Core |
| Automation * | Standard | **$30** | Core |

| **IT & legal** | | | |
| Comms | Light | **$20** | Core |
| InfoSec * | Standard | **$30** | Core |
| API & data platform | Standard | **$30** | Core |
| Progressive App | Light | **$20** | Core |
| Legal * | Light | **$20** | Core |

**Affiliates** is priced but still absent from the capability graph in the
product docs. The dependency on Core above is an assumption, not a record.

---

## 4. Platform Core — $50

Never discounted, on every quote, cannot be removed. Accounts and roles,
sign-in, the audit log, backups and restore, the document vault, the event bus,
hosting, and the support route.

**Included with every install, at no charge:** all three surfaces install to a
phone or desktop home screen as an app (PWA) — no store, no download, no review
queue. Push notifications with no per-message fee. Camera access for QR and
barcode scanning. Microphone for voice notes and calls. Offline tolerance with
sync on reconnect. One codebase covers iOS, Android and desktop.

This is worth saying out loud in every proposal. The alternative quote a client
is comparing against usually includes a native app build and two store
submissions per release.

---

## 5. Volume discount

| Capabilities | Discount |
|---|---|
| 1–2 | — |
| 3–5 | 8% |
| 6–9 | 15% |
| 10+ | 25% ⚠ |

Applies to capability lines only — never to Core, never to Part 2, never to
services. **The 10+ tier is broken.** See §15 item 1.

---

## 6. Packaged tiers

For clients who want a price rather than a configuration. **A tier is only
offered when it covers every capability the client needs**, and it is priced
*above* the equivalent menu at a single location — it buys headroom, not a
discount.

| | **Basic** | **Pro** | **Scale** |
|---|---|---|---|
| **Monthly** | **$200** | **$400** | **$700** |
| Locations | 1 | 3 | 10 |
| Staff seats | 5 | 20 | 75 |
| Capabilities | Selling, Payments, Workforce, Comms | + Inventory, Warehouse, CRM, Marketing, Subscriptions | + Distribution, Production, Sourcing, Events, Affiliates, Intelligence, Automation, API |
| Chatbot | — | 5,000 turns | 20,000 turns |
| Email | 10,000 | 50,000 | 200,000 |
| Group video | — | — | 50,000 participant-min |
| Voice | — | — | 3,000 min |

**Learning, Fundraising, Accounting, Finance, Treasury, Onboarding, Payroll,
InfoSec, Legal and Voice sit outside every tier.** Course businesses,
nonprofits and anyone who wants the finance stack buys the menu. That is the
honest answer, not a gap to be filled — a commerce tier that quietly includes
an LMS is a tier nobody can price.

Quote both, quote the cheaper one, and only count a tier if it covers the
selection.

---

## 7. Scale metric — optional, off by default

Capability pricing is flat: a client doing $50k a month and one doing $500k a
month pay the same. This is the optional correction.

| Active subscribers | Adds |
|---|---|
| up to 250 | included |
| 251 – 1,000 | +$50 |
| 1,001 – 2,500 | +$120 |
| above 2,500 | +$250 |

Active subscribers is the default metric because the bill run already walks
active contracts — you would be billing on a number the system computes
anyway. Orders or GMV bands work identically.

**Nothing depends on this being switched on.** It joins Part 1, so nonprofit
and annual discounts apply to it.

---

## 7b. Back office only — keep your website

Not every client wants us to build their site. Plenty already have one they
like, or one their marketing agency owns, or a Shopify they are not leaving.
Telling them the back office comes with a shop they have to ignore is how a
good fit is talked out of a sale.

**Back office only** is the same platform, the same capabilities, the same
price — with the storefront switched off and the door pointed at the site
they already have.

| | Back office only | Full install |
|---|---|---|
| Platform core | **$50** | $50 |
| Capabilities | as chosen | as chosen |
| Storefront | off — visitors go to their site | ours |
| Build | none, or a **$500** wiring setup | §12's ladder |
| Their website talks to it | scoped API key | not needed |

The monthly is identical because the cost to serve is identical: it is the
same install. What they save is the build, which is the honest saving and the
one worth naming — a client who hears "cheaper" and then sees the same monthly
figure stops believing the rest of the page.

**Wiring setup — $500.** Mint the key, point their developer at the four
calls that matter, and stay on the line while the first real order arrives.
Skippable: a client with a competent developer needs a key and an afternoon,
and charging them for a phone call they did not need is how the number stops
being trusted.

What their site does with it:

| It wants to | Call |
|---|---|
| Show what is for sale | `GET /api/store/catalog` |
| Place an order | `POST /api/orders` |
| Read their orders back | `GET /api/orders` |
| Hear about changes | Integrations → your own connection |

Everything else — stock, tills, rota, documents, analytics — is the back
office, and is used the same way it always is. The website is a customer of
the platform, not a part of it.

---

## 8. White-labelling

A licence, not a fork. Same code, same upgrades, same day — only marks,
domains and addresses differ. Zero marginal cost to serve, which makes it
close to pure margin.

| Level | Monthly | Setup | What it gets |
|---|---|---|---|
| **None** | $0 | — | Our mark stays in the footer and sign-in |
| **Unbranded** | **$50** | — | Our name and mark removed; client logo and colours throughout; transactional email from their address |
| **Branded install** | **$100** | $500 | + own domain across all three surfaces; own icon and splash on the installed app; authenticated sending domain (SPF/DKIM/DMARC); branded documents, invoices and client portal; push under their name |
| **Full white-label** | **$200** | $1,500 | + no reference to us anywhere reachable, including source comments, page titles and error pages; support answered under their name; their terms and cookie banner; rebadged documentation; suitable for reselling onward |

Monthly sits in Part 1. Setup joins the build.

---

## 9. Metered add-ons

Included allowances cost us money and earn nothing. Every line here can
instead be **passed through** — the client brings their own vendor key, and we
take neither the revenue nor the cost nor the risk.

| Add-on | Our cost | We charge | Included (menu) |
|---|---|---|---|
| AI support chatbot | $0.012 / conversation | **$0.036** | 200 |
| Group video (SFU) | $0.00075 / participant-min | **$0.0025** | 0 |
| Voice interface | $0.03 / min | **$0.09** | 0 |
| Email sends | $0.0001 | **$0.0003** | 10,000 |
| SMS | $0.008 | **$0.02** | 0 |
| Translation | $0.02 / 1k chars | **$0.06** | 0 |

**Unit conflict:** tiers quote the chatbot in *turns*, this table bills
*conversations*. They agree at exactly four turns per conversation and nowhere
else. Pick one unit. (§15 item 3.)

---

## 10. Seats, locations and devices

| | Included on the menu | Overage |
|---|---|---|
| Locations | 1 | +$29 each |
| Staff seats | 5 | +$7 each |
| Registers | 1 | +$19 each |
| Clock kiosks | 1 | +$6 each |

Billable seats are people who sign in to run the business. Customers,
students, donors and affiliates are always free — they are the point of the
software, not a cost centre.

A **register** is a till that can be open at once: a shop with three lanes
running simultaneously is three, whatever the tablets are called. It is priced
per lane rather than per device because that is what the client counts when
they picture the shop, and because a spare tablet in a drawer costs us
nothing until somebody opens a drawer with it.

A **clock kiosk** is a tablet bolted up for people to punch in on. Cheaper
than a register because it does one thing, has no money in it, and is the
device most likely to be a hand-me-down.

Both are counted against what the client is entitled to, and the count is
enforced rather than trusted: a fourth lane on a three-lane plan is refused
with the number in the message, because a limit that is only checked at
invoice time is a limit the client discovers a month after they broke it.

The menu's included allowance is an **assumption**, not a recorded decision:
v1 never stated one. Basic's figures are used. Write this down properly.

---

## 11. Cost to serve

Two figures were in conflict in v1. They are not in conflict; they are
different scopes.

**Platform line, per install** — itemised from the cluster rate card, then
multiplied by provider (Hetzner ×0.45, DigitalOcean ×1.0, AWS/GCP ×1.9):

| Line | Rate | Shared over |
|---|---|---|
| Node (VPS) | $20/mo | installs per node |
| Load balancer | $12 per 8 nodes | 8 × density |
| Control plane | $12/mo | all installs |
| Staging | $12/mo | all installs |
| Managed monitoring | $30/mo | all installs |
| Storage | $0.006/GB | per install |
| Offsite backups | $0.006/GB | per install |
| CDN egress | $0.01/GB | per install |
| TURN relay | $0.05/GB | per install |

**Per-install hosting is mostly a function of how many installs you have**,
not of the install:

| Installs on the platform | Hosting each |
|---|---|
| 1 | $55.08 |
| 5 | $11.88 |
| 10 | $6.48 |
| 25 | $3.24 |
| 100 | $1.62 |

The v1 "$3.50" figure is the cost at 25 installs. At your first client it is
$55. The margin thesis is true at scale and false at launch, and the gap is
roughly $50/month per client for the first handful. Budget for it.

Dedicated node: **$96/install**. Sell it as a tier, not a favour — it takes a
$305 subscription from ~98% to ~68% margin.

---

## 12. Services

Services are labour. They run at **30–50% margin** and scale with people, not
with installs. This is the only part of the business where selling more can
make you poorer.

### The one-time ladder

One ladder, not two. There used to be a platform build ladder and a studio
website ladder side by side, at the same prices, describing the same work
under different names — a client could be quoted $5,000 twice and asked to
choose. Every rung below is priced as a band rather than a figure, because
the shape of this work is known before the scope is: quote the tier, not the
hours, and land inside the band after discovery.

| Tier | From | To | Timeline | Revisions | What it is |
|---|---|---|---|---|---|
| **Guided setup** | **$500** | $500 | 1 week | — | We stand your install up, import what you have, configure the capabilities you picked and walk your team through it |
| **Week website** | **$1,500** | $4,000 | 5 working days | 1 round | Existing template, your content, up to 5 pages, no custom work |
| **Custom build** | **$5,000** | $15,000 | 4-6 weeks | 2 rounds | Template foundation, custom sections, a custom design pass, 5-15 pages |
| **Custom build + Branding & creative** | **$18,000** | $60,000 | 8-16 weeks | 2 rounds per phase | Designed from scratch with the identity made alongside it: bespoke functionality, unlimited pages, motion system |
| **Branding & creative** | **$6,000** | $40,000 | 4-10 weeks | 2 rounds per deliverable | Identity, art direction, motion, campaign assets - sold alongside any rung, or on its own |

**Guided setup is not a build.** It is the hour where an install becomes
yours; it sits at the bottom of the ladder because it is the cheapest way in,
not because it is a small website.

A build may be split by surface, which is how clients think and how scope
arguments are avoided. A $5,000 custom build splits:

| Surface | Share |
|---|---|
| Customer storefront | $2,000 |
| Store admin & theme | $1,000 |
| ERP & CRM ops | $1,500 |
| Integrations & data migration | $500 |

Surfaces are the right unit for the **build** because they are a real boundary
in the product. They are the wrong unit for the **subscription**, because
capabilities cut across all three.

The client-facing rate card (`03-proposal/rate-card.md`) shows the same
ladder and must agree with this table.

### Care plan — Part 2 of the monthly bill

| | **Essential** | **Standard** | **Priority** |
|---|---|---|---|
| **Monthly** | **$150** | **$350** | **$750** |
| First response | 3 working days | 1 working day | Same day |
| Defect targets | P3 | P2 | P1, 24/7 for outages |
| Updates | Monthly | Fortnightly | Weekly |
| Critical patches | 24h, any day | 24h, any day | 24h, any day |
| Restore tested | Annual | Quarterly | Quarterly |
| Key journeys watched | — | Every 15 min | Every 15 min |
| Error & performance monitoring | — | ✓ | ✓ |
| Out-of-hours response | — | — | ✓ |
| Named engineer | — | — | ✓ |
| Content changes included | — | 1 hour | 4 hours |
| Emergency support | Hourly | 50% off | Included |
| Discount on new work | — | 10% | 15% |

Full contents, exclusions and the three schedules are in
`care-plan-agreement.md` and its schedules. Send all four together.

**Delivery hours are the whole economics.** At $45/hour cost:

| | 1h/mo | 2h | 4h | 6h |
|---|---|---|---|---|
| Essential $150 | 70% | 40% | **−20%** | −80% |
| Standard $350 | 87% | 74% | 49% | 23% |
| Priority $750 | 94% | 88% | 76% | 64% |

Hours before each plan drops under the 30% floor: Essential **2.3h**, Standard
**5.4h**, Priority **11.7h**. Essential goes underwater somewhere around
three hours — which is not many, for a plan promising 24-hour critical
patching.

### Growth retainer — a separate agreement

$600 Foundation / $1,500 Momentum / $3,000 Campaign. Sold at the first review
after launch, never at handover. Ad spend is paid by the client to the
platform, never marked up, never held. Minimum three months. Details in
`growth-retainer.md`.

### Studio — $750 Lite / $2,500

Design retainer. Outside both discounts, billed all twelve months.

---

## 13. Bundles

Recomputed under the bands. These are derived, not decided — if one looks
wrong, the band assignment is wrong, not the bundle.

| Bundle | Capabilities | Sum | Volume | Other | **Monthly (Part 1)** |
|---|---|---|---|---|---|
| Food brand | 12 | $380 | −25% | — | **$335.00** |
| Course business | 8 | $280 | −15% | — | **$288.00** |
| Language nonprofit | 8 | $250 | −15% | 30% nonprofit | **$183.75** |
| Food bank | 10 | $300 | −25% | 30% nonprofit | **$192.50** |
| Commerce + course | 10 | $340 | −25% | — | **$305.00** |

And *which* capabilities, because a count is not a set. A bundle that says
twelve without naming them cannot be bought, granted or checked — the shop
would be selling a number.

| Bundle | Capability ids |
|---|---|
| Food brand | `selling, payments, inventory, warehouse, distribution, workforce, events, comms, crm, marketing, intelligence, subs` |
| Course business | `selling, payments, learning, workforce, comms, crm, marketing, intelligence` |
| Language nonprofit | `learning, fundraising, payments, workforce, events, comms, crm, intelligence` |
| Food bank | `inventory, warehouse, distribution, fundraising, payments, workforce, events, comms, crm, intelligence` |
| Commerce + course | `selling, payments, learning, inventory, workforce, comms, crm, marketing, intelligence, subs` |

Each set must reproduce its own row above: the count is the length of the
list and the sum is the list priced at the bands. If they disagree the
bundle is wrong, not the arithmetic.

Add Part 2 on top. A commerce + course client on a Standard care plan bills
**$655/month** — $305 platform, $350 support.

---

## 14. Discounts and terms

- **Nonprofit** — 30% off the Part 1 subtotal. Never off services.
- **Annual** — two months free, applied to what remains after nonprofit. Costs
  17% of subscription revenue; it is the largest discount in the book and it
  compounds with nonprofit (a nonprofit on annual pays 42% less than list).
- **Studio and the care plan are charged all twelve months** and sit outside
  both.

---

## 15. Still open

1. **The 10+ volume discount inverts.** At 25%, a client with nine
   capabilities pays **$313.50** and one with ten pays **$305.00** — an extra
   capability makes the bill $8.50 cheaper. At this basket, anything under
   $41.33 pays for itself. **Setting the tier to 20% fixes it:** $313.50 →
   $322.00. One number. It has been known for a while now.
2. **Tier coverage sets (§6) are new and have no decision record behind them.**
   They were assigned to make "quote the cheaper one" computable. They decide
   which clients can buy a tier at all, which makes them a pricing decision
   wearing an implementation hat. Ratify or rewrite them.
3. **Chatbot unit conflict** — turns in the tiers, conversations in §9. They
   agree only at exactly 4 turns.
4. **The menu's seat and location allowance is assumed**, not decided (§10).
5. **Affiliates is priced but not in the capability graph.**
6. **Three architecture questions still gate this** — fixed vs curated boxes,
   who owns inventory truth, who owns the customer record. The first one
   directly decides whether Subscriptions & boxes is a $30 capability or an
   allocation engine you have to build. Pricing it before that is settled is
   pricing a guess.
7. **Install density is modelled, not measured.** "25 installs per node" is the
   single most load-bearing guess in the pricing, and every margin figure moves
   with it.
8. **Nothing here is measured.** No client has yet paid any of these prices.

---

## 16. Vocabulary

Used consistently here, and worth enforcing everywhere else:

| Thing | Word |
|---|---|
| A person who signs in | **user** — their record is an account |
| The business paying us | **client** |
| A shopper, student, donor or affiliate inside their system | **customer** |
| The isolated data + config unit | **install** |
| The routing and database abstraction | **tenant** — internal code only |
