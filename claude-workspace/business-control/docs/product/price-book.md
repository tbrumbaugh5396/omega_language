# Price book — capabilities, dependencies, cost and price

**Internal. Never send this to a client.** They get the [capability
menu](../business-control-b2b-client/templates/02-consultation/capability-menu.md),
which is this document with the cost and margin columns taken out.

**Written August 2026**, from the three data models inside
[`ecommerce-stack-deck.html`](ecommerce-stack-deck.html) — the capability graph
(lines 708–789), the internal cost model (1091–1179), and the customer price
book (1552–1621). Those three had already drifted from each other; §8 is the
list of every place they disagree, carried here rather than quietly resolved.

> **Nothing here is measured.** Every figure is modelled, several are marked
> *(verify)* at source, and the load-bearing "25 tenants per node" is an
> engineering estimate (deck 2330). Treat this as the shape of the pricing, not
> as the pricing.

---

## 1. The capabilities, and what each one needs

Every capability, its dependencies both ways, our marginal cost to serve it and
the list price. **Requires** is what turns on with it, whether the customer
asked or not. **Unlocks** is what becomes available once it is on.

| Capability | Group | Requires | Unlocks | Includes | Our cost | List | Margin |
|---|---|---|---|---|---|---|---|
| **Platform Core** | *always on* | — | everything | accounts · roles · PWA · push · backups · support desk | $2 | **$49** | 96% |
| Sourcing | Operations · Supply chain | Core | — | suppliers · POs · ingredients | $0 | $15 | 100% |
| Production | Operations · Supply chain | **Inventory** | — | batches · lots · expiry | $0 | $25 | 100% |
| Inventory | Operations · Supply chain | Core | Production · Warehouse · Distribution | stock · par levels · counts | $0 | $19 | 100% |
| Warehouse | Operations · Logistics | **Inventory** | — | bins · pick lists · load QR | $0 | $15 | 100% |
| Distribution | Operations · Logistics | **Inventory** | — | routes · fleet · truck QR · ETAs | $0 | $29 | 100% |
| Learning | Operations | Core | Voice & translation | lessons · SRS · curriculum · progress | $0 | $35 | 100% |
| Voice & translation | Operations | **Learning** | — | recording · STT · translation | $0 | ⚠ **no price** | — |
| Selling | Revenue ops · Sales | Core | Subscriptions & boxes | products · variants · carts · orders · promos · media | $0 | $29 | 100% |
| Subscriptions & boxes | Revenue ops · Sales | **Selling + Payments** | — | cycles · cutoffs · dunning · curation · portal | $0 | $25 | 100% |
| Fundraising | Revenue ops · Sales | **Payments** | — | recurring giving · receipts · grants | $0 | $19 | 100% |
| Marketing | Revenue ops | Core | — | email playbooks · A/B · pixels | $0 | $25 | 100% |
| CRM & Support | Revenue ops | **Comms** | — | outreach pipeline · support desk · LLM bot | $0 | $19 | 100% |
| Events | Revenue ops | **Workforce** | — | event clock-ins · promo landings | $0 | $9 | 100% |
| Affiliates | Revenue ops ⚠ | *(not in the graph)* | — | links · landing pages · attribution | $0 | $15 | 100% |
| Payments | Finance | Core | Subscriptions · Fundraising · Finance | Stripe/Shopify rails · COD · terms · refunds · receipts | $0 | $15 | 100% |
| Accounting | Finance | Core | Finance | ledger · categories · exports | $0 | ⚠ **no price** | — |
| Finance | Finance | **Payments + Accounting** | Treasury | cash view · budgets · forecasts | $0 | ⚠ **no price** | — |
| Treasury & investments | Finance | **Finance** | — | cash · assets · positions | $0 | ⚠ **no price** | — |
| Workforce | Human resources | Core | Events · Onboarding · Payroll | time clock · jobs · shifts · kiosk · 1099 | $0 | $19 | 100% |
| Onboarding | Human resources | **Workforce** | — | hiring docs · certs · checklists | $0 | ⚠ **no price** | — |
| Payroll | Human resources | **Workforce** | — | timesheets → pay · 1099 | $0 | ⚠ **no price** | — |
| Intelligence | Management | Core | — | funnel · P&L · HQ view | $0 | $29 | 100% |
| Automation | Management | Core | — | triggers · rules · schedules · approvals | $0 | ⚠ **no price** | — |
| Comms | Information technology | Core | CRM & Support | chat · voice · video calls (TURN relay) | **$1.50** | $19 | 92% |
| InfoSec | Information technology | Core | — | SSO · audit logs · access reviews | $0 | ⚠ **no price** | — |
| API & data platform | Information technology | Core | — | public API · scoped keys · webhooks · exports | $0 | $25 | 100% |
| Legal | Legal | Core | — | contracts · policies · docs | $0 | ⚠ **no price** | — |

**Nine capabilities carry no price** and one carries a price with no place in
the graph. Both are listed in §8 rather than invented here.

### The chains that actually bite

Core is under everything and is never optional, so it is left out below. What
remains is the set of picks that drag another pick with them:

```
Core ──┬── Inventory ──┬── Production
       │               ├── Warehouse
       │               └── Distribution
       │
       ├── Selling ──────┐
       ├── Payments ──┬──┴─ Subscriptions & boxes   (needs BOTH)
       │              ├──── Fundraising
       │              └──┐
       ├── Accounting ───┴─ Finance ── Treasury     (Finance needs BOTH)
       │
       ├── Workforce ─┬── Events
       │              ├── Onboarding
       │              └── Payroll
       │
       ├── Learning ───── Voice & translation
       │
       └── Comms ──────── CRM & Support
```

Read it as: **you cannot buy the right-hand thing without the left-hand thing.**
Two of them need two parents — Subscriptions needs Selling *and* Payments;
Finance needs Payments *and* Accounting, which makes Treasury a three-deep pick.

Everything not on this tree hangs straight off Core and can be bought alone:
Sourcing, Marketing, Intelligence, Automation, InfoSec, API, Legal, Affiliates.

---

## 2. The capabilities by group

The same list, in the columns the product is organised in. This is the view to
read when you are working out what a business of a given shape needs.

### Operations

| | Requires | Our cost | List |
|---|---|---|---|
| **Supply chain** — Sourcing | Core | $0 | $15 |
| **Supply chain** — Inventory | Core | $0 | $19 |
| **Supply chain** — Production | Inventory | $0 | $25 |
| **Logistics** — Warehouse | Inventory | $0 | $15 |
| **Logistics** — Distribution | Inventory | $0 | $29 |
| Learning | Core | $0 | $35 |
| Voice & translation | Learning | $0 | ⚠ no price |

### Revenue operations

| | Requires | Our cost | List |
|---|---|---|---|
| **Sales** — Selling | Core | $0 | $29 |
| **Sales** — Subscriptions & boxes | Selling + Payments | $0 | $25 |
| **Sales** — Fundraising | Payments | $0 | $19 |
| Marketing | Core | $0 | $25 |
| CRM & Support | Comms | $0 | $19 |
| Events | Workforce | $0 | $9 |
| Affiliates ⚠ | *(not in the graph)* | $0 | $15 |

### Finance

| | Requires | Our cost | List |
|---|---|---|---|
| Payments | Core | $0 | $15 |
| Accounting | Core | $0 | ⚠ no price |
| Finance | Payments + Accounting | $0 | ⚠ no price |
| Treasury & investments | Finance | $0 | ⚠ no price |

### Human resources · Management · IT · Legal

| | Group | Requires | Our cost | List |
|---|---|---|---|---|
| Workforce | HR | Core | $0 | $19 |
| Onboarding | HR | Workforce | $0 | ⚠ no price |
| Payroll | HR | Workforce | $0 | ⚠ no price |
| Intelligence | Management | Core | $0 | $29 |
| Automation | Management | Core | $0 | ⚠ no price |
| Comms | IT | Core | $1.50 | $19 |
| InfoSec | IT | Core | $0 | ⚠ no price |
| API & data platform | IT | Core | $0 | $25 |
| Legal | Legal | Core | $0 | ⚠ no price |

---

## 3. Bundles — the menu a customer actually picks from

A bundle is not a separate SKU. It is a saved selection of capabilities, and it
beats picking the same boxes one at a time only because of the volume discount
(3+ = 8%, 6+ = 15%, 10+ = 25%).

| Bundle | Boxes | À la carte | Volume | + Core | **Monthly** | Our cost | Margin |
|---|---|---|---|---|---|---|---|
| 🍜 **Food brand** | 12 | $252 | −25% → $189.00 | +$49 | **$238.00** | $3.50 | 98.5% |
| 🎓 **Course business** | 8 | $190 | −15% → $161.50 | +$49 | **$210.50** | $3.50 | 98.3% |
| 🗣 **Language nonprofit** | 8 | $164 | −15% → $139.40 | +$49 | $188.40 · −30% np → **$131.88** | $3.50 | 97.3% |
| 🥫 **Food bank** | 10 | $192 | −25% → $144.00 | +$49 | $193.00 · −30% np → **$135.10** | $3.50 | 97.4% |

Our cost is $3.50 for all four: $2 of Core plus $1.50 of Comms relay. Every
other capability is software we have already written, and software costs
nothing to serve a second customer. That is the whole pricing thesis, and it is
why the metered lines in §5 are metered — those are the only ones where serving
more costs more.

### 🍜 Food brand — $238/mo

Selling · Payments · Inventory · Warehouse · Distribution · Workforce · Events ·
Comms · CRM & Support · Marketing · Intelligence · Subscriptions & boxes

> Dependency-complete as it stands: Warehouse and Distribution already have
> Inventory, Subscriptions has Selling and Payments, CRM has Comms, Events has
> Workforce. Nothing gets dragged in unasked.

### 🎓 Course business — $210.50/mo

Selling · Payments · Learning · Workforce · Comms · CRM & Support · Marketing ·
Intelligence

> The graph's version of this bundle also carries Voice & translation; the
> price book's does not, and Voice & translation has no price — see §8 #7.

### 🗣 Language nonprofit — $131.88/mo *(after −30%)*

Learning · Fundraising · Payments · Workforce · Events · Comms · CRM & Support ·
Intelligence

> Fundraising needs Payments, which is in the bundle. Same Voice & translation
> divergence as the course bundle.

### 🥫 Food bank — $135.10/mo *(after −30%)*

Inventory · Warehouse · Distribution · Fundraising · Payments · Workforce ·
Events · Comms · CRM & Support · Intelligence

> No Selling — a food bank moves stock without charging for it. This is the
> bundle that shows the graph is real: take Inventory out and three other picks
> fall over.

---

## 4. Packaged tiers

The alternative to picking boxes: a flat tier with quotas. Sold to customers who
want a price rather than a configuration, and the thing an à-la-carte account
eventually grows into.

| | **Starter** | **Pro** ★ | **Scale** |
|---|---|---|---|
| **Monthly** | **$49** | **$149** | **$399** |
| Locations included | 1 | 3 | 10 |
| Staff seats included | 5 | 20 | 75 |
| Roughly | Commerce Core + Workforce | + Operations & CRM | + Growth & Intelligence |
| Chat · push · 1:1 calls | ✓ | ✓ | ✓ |
| TURN relay (calls that need it) | — | ✓ | ✓ |
| AI support chatbot | — | 5,000 turns | 20,000 turns |
| Group video (SFU) | — | — | 50,000 participant-min |
| Voice interface | — | — | 3,000 min |
| Translation | — | — | 500 × 1k chars |
| Email included | 10,000 | 50,000 | 200,000 |
| SMS included | — | — | 3,000 |
| Backups | ✓ | ✓ | ✓ |
| Support | email | priority chat | dedicated + onboarding call |

Beyond the quotas: locations +$29, seats +$7, metered units at the §5 overage
prices. **Billable seats are people who sign in to run the business** —
customers, donors, students and affiliates are always free, or a storefront with
ten thousand shoppers is unsellable.

> The up-tier conversation writes itself: seats and locations are what push an
> account over the line, and at some size the flat tier is simply cheaper than
> the boxes. Compute both and show the customer the cheaper one.

---

## 5. Metered add-ons — the only lines that cost us anything

The rule the whole model rests on: **anything a vendor prices per-minute or
per-message becomes a metered add-on. Only flat-cost features go in flat
tiers.** That is what bounds the serving cost of every tier.

| Add-on | Unit | Included | Our cost | List | Multiple |
|---|---|---|---|---|---|
| AI support chatbot | conversation | 200 | $0.012 | $0.036 | 3.0× |
| Group video (SFU) | participant-min | 0 | $0.00075 | $0.0025 | 3.3× |
| Voice interface | minute | 0 | $0.03 | $0.09 | 3.0× |
| Email sends | email | 10,000 | $0.0001 | $0.0003 | 3.0× |
| SMS | message | 0 | $0.008 | $0.02 | 2.5× |
| Translation | 1k characters | 0 | $0.02 | $0.06 | 3.0× |

**Included allowances are served at cost with no revenue** — the quote only
bills the overage. Ten thousand included emails is a real dollar of cost against
zero dollars of income, by design, and it is the reason the allowances are as
small as they are.

The two that can eat a margin: **group video**, priced per participant-minute
so it scales with usage rather than with customers, and the **voice interface**,
where $0.03/min sounds like nothing until a kiosk runs it all day.

### What we actually buy

| Line | Rate | Notes |
|---|---|---|
| Nodes (VPS) | ceil(tenants ÷ 25) × $20 | one 4 GB node carries ~25 tenants — *modelled, not measured* |
| Chat · push · 1:1 calls | $0 | built-in (WebSocket, VAPID, WebRTC P2P) — against Intercom at $39–99/seat |
| TURN relay | $0.05/GB | P2P fails on ~10–20% of networks; required before selling calls |
| Group video (SFU) | $0.00075/participant-min | LiveKit / Daily |
| LLM chatbot | $0.003/turn | Claude Haiku 4.5 at $1/$5 per MTok, cached catalogue prompt |
| Voice (STT+TTS) | $0.03/min | blended |
| Translation | $0.02/1k chars | |
| Email | SES $0.10/1k · Postmark $15 + $1.25/1k over 10k · SendGrid $19.95 to 50k then $0.89/1k | |
| SMS | $0.008/msg + $1.15/number | Twilio |
| Offsite backups | $0.006/GB | Backblaze B2 |
| Shopify plan | $39/mo per tenant on the Shopify rail | **pass-through** |
| Payment processing | 2.9% + 30¢ (Advanced 2.5% + 30¢) | **pass-through** |

Cluster planning uses a second rate card: node $24 (25 units), load balancer $12
per 8 nodes, dedicated node $96, control plane $12, staging $12, storage
$0.006/GB, CDN egress $0.01/GB, backups $0.006/GB, managed monitoring $30 —
multiplied by provider: Hetzner ×0.45, DigitalOcean ×1.0, AWS/GCP ×1.9.

---

## 6. Services — the other axis

Sold **alongside** a subscription, never instead of one.

| Build (one-time) | Price | What it is |
|---|---|---|
| No build — self-serve | $0 | they configure it themselves |
| Guided setup | $499 | import, config, launch checklist · 1 week |
| Launch build | $5,000 | theme, brand tokens, sections, migration · 2 weeks |
| Custom build | $18,000 | bespoke sections, motion, integrations · 6 weeks |
| Flagship | $40,000 | brand + build + motion system · 10 weeks |

| Studio (monthly) | Price | What it is |
|---|---|---|
| No Studio | $0 | — |
| Studio Lite | $750 | 1 active request · refreshes · templates |
| Studio | $2,500 | brand system · campaigns · motion |
| Flagship | project · $40k+ | identity, motif system, film, art direction — ends in a retainer |

Software runs at ~96% gross margin and scales without headcount. Services run at
30–50% and scale with people. Services are ~60% of revenue in year one and ~25%
by year three — and the build fee is negative CAC: $18,000 paid to us to acquire
an account worth ~$14,364 over three years at $399/mo.

> Price services slightly uncomfortably, so the product stays the easy path.
> Each build reuses ~80% of the platform and should reach 90% by the tenth —
> same price to the client, materially less delivery cost to us, which is not
> normally true of services.

---

## 7. How a quote is assembled

Order matters, and it is not the order anyone guesses:

```
   sum of chosen boxes
 × volume discount            3+ = 8% · 6+ = 15% · 10+ = 25%
 + Platform Core              $49, never discounted
 + metered overage            usage beyond the included allowance
 + seat & location overage    +$7 · +$29
 ─────────────────────────
 = subtotal
 − nonprofit                  30% of the subtotal
 − annual                     2/12 of what remains (two months free)
 ─────────────────────────
 = monthly, billed
 + Studio retainer            added AFTER both discounts
 + build fee                  one-time, due today, outside the monthly
```

---

## 8. ⚠ Disputed and missing

Every place the sources contradict each other or leave a hole. Both values are
carried; nothing here has been silently decided.

| # | Item | One source says | The other says | Where |
|---|---|---|---|---|
| 1 | **AI chatbot metering** | $0.009 per **bot turn** | $0.036 per **conversation** | `METER.bot.ov` (deck 1164) vs `XQ_METERS` (1578). Identical economics at 4 turns per conversation — but merge them naively and you are out by 4× |
| 2 | **Node cost** | $20 | $24 · $15–24 · $6–24 | `QF.node` (1094) vs `CL_RATES` (1413) vs `saas-scaling.md:41` vs deck 152 |
| 3 | **Affiliate attribution** | 30-day | 7-day | deck 2213 vs 2926 |
| 4 | **Test count** | 147 passing checks | 149 passing checks | deck 15 vs 2192/2302/453 |
| 5 | **Nine capabilities have no price** | in the graph, sellable | absent from the price book | Voice & translation · Accounting · Finance · Treasury · Onboarding · Payroll · InfoSec · Automation · Legal |
| 6 | **Affiliates** | priced at $15 | not in the capability graph at all | `XQ_BOXES` 1571 — no `BOXES` entry, so it has no group and no dependencies |
| 7 | **Bundle divergence** | course & lingua include Voice & translation | they don't | `BUNDLES` 774–775 vs `XQ_BUNDLES` 1587–1588 — and the capability it disagrees about is one of the nine with no price |
| 8 | **Drawn arrows ≠ declared dependencies** | Sourcing→Production, Warehouse→Distribution, InfoSec→API | Production needs Inventory, Distribution needs Inventory, API needs Core | `EDGES` 738–744 vs the `dep` arrays. The picture and the rule disagree, so the diagram cannot be generated from the data |
| 9 | **Enterprise tier** | a fourth class at $1,200/mo | only three tiers exist | `CL_CLASSES` 1409 vs `XQ_TIERS` 1596–1599 |
| 10 | **Care plan monthly** | $150 / $350 / $750 | $150–300 / $300–600 / $600–1,500 | kit `care-plan-agreement.md` vs `rate-card.md:58–60` |
| 11 | **Kit package naming** | four contract tiers (week website · partially custom · fully custom · branding) | three client options A/B/C, *and* four sizing-score packages | three naming systems in one kit, nothing reconciles them |
| 12 | **Studio & the annual discount** | Studio is added after both discounts | the annual figure (`billed × 12`) omits Studio entirely | deck 1725 / 1751 / 1757 — reads like a model bug, not a decision |
| 13 | **Cost to serve a Pro tenant** | $8–12/mo | ~$3.50/mo | `saas-scaling.md:60` (share of node + real LLM usage) vs the à-la-carte marginal cost. Two different cost bases, both labelled "our cost" |
| 14 | **Seat overage $7** | in the price book and the Starter description | absent from the prose pricing paragraph | deck 1595 vs 161–164 |
| 15 | **Duplicated constants** | 49/149/399 written in three places; six vendor unit costs in two | — | `QTIERS` · `CL_CLASSES.mrr` · `XQ_TIERS`; `QF` vs `XQ_METERS` |
| 16 | **Included allowances** | quoted as a customer benefit | cost us money and earn nothing | deck 1713 — by design, but it belongs in the margin conversation |
| 17 | **Pass-throughs** | Shopify $39/mo and 2.9% + 30¢ appear in the cost calculator | neither is our cost nor our revenue | easy to double-count into a margin figure that isn't real |

---

## What to do with this

The next pass is yours: settle §8, then this document becomes the one place
prices live and the deck should read from it rather than carrying its own
copies. Until then, **the deck and this file will drift** — the same way the
deck already drifted from the three decision documents it was built from
(`README.md:68`).
