# Ecommerce platform decision: Shopify vs. custom build

**Context:** Physical goods + subscription boxes. In-house coding, web-dev, and graphic design capability. 
An existing in-progress CRM/ERP intended to run the back office.

**Document date:** August 2026. 
Pricing, deprecation dates, and vendor positions change — verify anything time-sensitive against primary sources before committing.

---

## 1. Executive summary

The instinct that "Shopify isn't right for us" is aimed at the wrong layer. 
Shopify bundles two very different things, and they should be evaluated separately:

| Layer | What it is | Should you own it? |
|---|---|---|
| **Back office** | Admin UI, product records, order management, customer lists, reporting | Commoditised. Your ERP replaces it. No real loss. |
| **Money edge** | Hosted checkout, Shop Pay conversion, PCI scope, tax calculation, fraud scoring, card account updater / network tokens, off-session SCA, subscription billing rails | Very expensive to replicate. Rent it. |

**Recommendation:** headless Shopify. 
Your own storefront (Python full-stack PWA), your own ERP as system of record, your own subscriber portal — with Shopify acting as a payments-and-checkout appliance and a third-party app supplying subscription billing infrastructure.

This keeps every interesting problem in-house and rents only the parts that are pure liability.

---

## 2. What building the whole thing yourself actually costs

The storefront is the easy part and the part your skills map to. 
The expensive part is everything behind it.

- **Payments and PCI.** You'll use Stripe/Adyen either way, but you own the integration, 3DS/SCA flows, retries, saved cards, refunds, disputes, and the compliance surface.
- **Tax.** US sales-tax nexus across states, EU VAT/OSS, marketplace facilitator rules. This becomes an Avalara/TaxJar subscription plus ongoing logic, not a one-time build.
- **Fraud and chargebacks.** Shopify's fraud signals derive from network-wide data you cannot replicate at any budget.
- **Checkout conversion.** Shop Pay's one-tap flow converts measurably better than a checkout you build in three weeks. This is the single most underrated line item in the whole comparison.
- **The boring long tail.** Discount stacking, gift cards, returns/RMA, abandoned-cart flows, multi-location inventory, multi-currency, address validation, order editing, accounting exports, GDPR/CCPA deletion requests.
- **Ops.** Uptime during a launch spike, on-call rotation, backups, PCI scope maintenance. Permanently.

None of this is intellectually hard. 
It is simply a large volume of work that never stops, and it will consume the time you would rather spend on product and design.

### When a fully custom build genuinely wins

- The business model doesn't fit a product/variant/cart shape — marketplaces, complex quoting, heavy configurators, usage-based or hybrid billing.
- You already have a backend owning inventory and pricing, and the store is a thin layer on top of it.
- Deep B2B: contract pricing, approval workflows, credit terms, ERP as source of truth.
- The commerce experience *is* the product and is a real differentiator.
- Volume where platform fees clearly exceed a dedicated team's cost — realistically a $10M+/yr conversation, not a launch conversation.

### Open-source starting points if you go fully custom

| Project | Stack | Licence | Notes |
|---|---|---|---|
| Medusa | Node / TypeScript | MIT | Most active; good modular architecture |
| Saleor | Python / GraphQL | BSD-3 | Closest fit to a Python team |
| Vendure | TypeScript / NestJS | MIT | Strong admin, good plugin model |

These give you the domain model and an admin for free while you still own the code.

---

## 3. Subscription boxes change the calculus

Boxes make the case for a platform **stronger** on the billing side and **weaker** on the product side.

### 3.1 The money layer you really don't want to build

- **Dunning.** Failed payments cause 20–40% of involuntary churn. Retry schedules must be tuned per decline code — a naive "retry in 3 days" loses money continuously.
- **Card account updater / network tokens.** Cards expire constantly. Without automatic updates from Visa/Mastercard you bleed subscribers for no reason. This requires gateway-level relationships you can't self-serve into.
- **Off-session SCA / 3DS.** Selling into the EU/UK means recurring charges need mandate handling and exemption logic. Fiddly and unforgiving.
- **Prepaid plans.** 3/6/12-month prepaid boxes create deferred revenue, proration on cancel, and refund maths your accountant will care about.

Weeks to reach "works." 
Years to reach "works as well as Recharge." 
Also the least interesting code you will ever write.

### 3.2 Where Shopify will actively annoy you

Subscription boxes are the use case Shopify's data model handles worst.
- **Billing cadence ≠ shipping cadence.** The selling-plan model assumes charge and fulfilment are the same event. Boxes usually aren't: bill on the 1st, curate by the 8th, ship on the 15th. You get this from the app layer, not the platform.
- **Build-a-box.** Shopify's native Bundles app can't handle subscription items, which pushes you into writing custom Cart Transform Functions (Wasm) that you then own and maintain.
- **The subscriber portal.** This is where retention is won and it's the most constrained surface on the platform. The native portal lives inside Customer Accounts and supports pause, skip, cancel, and payment updates; customising it means React-based Customer Account UI Extensions, and a heavily branded portal hits their rendering limits quickly. For a box brand — where "swap this month's item," "skip December," "add a one-time upsell" *is* the product — that ceiling matters.
- **Variable box contents.** Curated boxes whose SKU composition changes per cycle fight the product/variant model constantly. Expect metaobjects plus a curation service of your own regardless of platform.

### 3.3 The cost stack

Fees compound on a subscription business: payment processing (~2.9% + 30¢) + platform fee + subscription-app fee + per-order fee.

As of mid-2026, Recharge and Skio charge roughly $0.19–$0.20 per subscription order plus a percentage; Smartrr carries a platform fee but no per-order fee, with a crossover point around $100K/month in subscription GMV. 
**Verify current pricing directly — this moves frequently.**

At ~$100K/mo subscription revenue you're looking at low four figures monthly for the subscription layer alone. 
Real money, but still cheaper than an engineer. 
The maths only flips well into eight figures.

### 3.4 Vendor landscape and concentration risk

Recharge acquired Skio in April 2026 for $105M cash. 
Signing with Skio today is functionally signing with Recharge. 
Loop and Smartrr are the notable remaining independents; Bold, Stay AI, Appstle, Awtomic, and Ordergroove make up the rest of the field.

If you're choosing infrastructure you'll operate for a decade — and a subscriber acquired in 2026 may still be active in 2031 — that consolidation is worth weighing in the decision.

---

## 4. The CRM/ERP question

### 4.1 What it does and doesn't replace

An ERP replaces Shopify's **back office** entirely. 
It replaces **none** of the money edge. 
Since the money edge is where nearly all the value and nearly all the pain live, the ERP makes Shopify's admin redundant — but the admin was the cheap, commoditised part you were never really paying for.

If anything, owning an ERP makes headless Shopify *more* attractive.
Shopify stops being "the platform" and becomes a thin sales-and-payments channel hanging off your system of record. 
That's a clean architecture, and arguably the right one for a box business, where the interesting logic (curation, allocation, forecasting, cohort economics) has to live somewhere Shopify was never going to host.

### 4.2 The real cost is the sync layer

Chronically underestimated:

- **Webhook reliability.** Delivery is at-least-once and occasionally never. You need idempotency keys, a replay queue, and a nightly reconciliation job that diffs both sides and alerts on drift.
- **Inventory truth.** Two systems both believing they know stock levels is how you oversell a box drop. Pick one owner; make the other strictly derived.
- **Bulk operations.** GraphQL Admin uses a query-cost budget, so large syncs need the Bulk Operations API rather than pagination loops.
- **API versioning.** Shopify ships quarterly API versions with a limited support window. Budget a few days per year, forever, just to stay current.

### 4.3 "Finishing up" is doing heavy lifting in that sentence

ERPs are where small teams disappear. 
Scope typically still outstanding: purchase orders and receiving, supplier lead times, lot/expiry tracking (matters for consumables), 3PL/WMS integration, returns and RMA, multi-location allocation, role-based permissions, audit logging, and an accounting export your bookkeeper trusts. 
Each is roughly a week. There are about twenty of them.

Bus factor is also real. 
A custom ERP means the operational nervous system is owned by whoever wrote it. 
Fine at three people; a liability at fifteen; a diligence problem if you ever raise or sell.

### 4.4 Build the specific parts, buy the generic parts

**Build** (specific to running a box business, nobody sells it well):
- Curation and allocation engine — which SKUs, in which box, for which subscriber segment, this cycle
- Demand forecasting against known subscriber counts and expected skip rates
- Cohort / LTV / churn analytics
- Cycle cutoff orchestration

**Buy or integrate** (commodity):
- Inventory and purchasing — Inventory Planner, Katana, Cin7
- Shipping labels and rates — EasyPost, Shippo
- Accounting — QuickBooks / Xero. **Do not build a general ledger.**
- Warehouse — your 3PL's own WMS
- Subscription billing — Loop / Recharge / Smartrr
- Checkout — Shopify

Result: an ERP-shaped thing at roughly 30% of the code and 100% of the differentiation.

---

## 5. Recommended architecture

```
┌─────────────────────────┐        ┌──────────────────────────┐
│  Your Python storefront │        │   Your CRM / ERP         │
│  FastAPI or Django      │        │   System of record       │
│  PWA shell, HTMX/JS     │        │   Curation, forecasting  │
│  Subscriber portal      │        │   Purchasing, analytics  │
└───────────┬─────────────┘        └────────────┬─────────────┘
            │                                   │
   Storefront API                        Admin GraphQL API
   (GraphQL, public token)               (server-side token only)
            │                                   │
            ▼                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                          SHOPIFY                             │
│                                                              │
│   cartCreate  ──►  checkoutUrl  ──►  Hosted checkout         │
│   (+ sellingPlanId)                  Payment, tax, fraud     │
│                                              │               │
│                                              ▼               │
│                                    Subscription contract     │
│                                    Recurring billing         │
└──────────────────────────────────────────────────────────────┘
                            │
                     Webhooks (orders, fulfilment, subscriptions)
                            │
                            ▼
                    Back to your ERP
```

### 5.1 The payment flow in detail

You never touch a card number.

1. Customer browses your Python-rendered storefront. Product data comes from the Storefront API.
2. Add-to-cart calls `cartCreate` / `cartLinesAdd`. For a subscription line, attach the `sellingPlanId`.
3. Shopify returns a `checkoutUrl`. You redirect the browser there.
4. Shopify collects payment, calculates tax, runs fraud checks, and — because the line carries a selling plan — vaults the payment method and creates a subscription contract.
5. Every subsequent charge is Shopify billing the customer autonomously. **No request from your code, ever.**
6. Webhooks notify your ERP of orders, fulfilment, and subscription state changes.

**Therefore: no separate payment processor, no Stripe account, no PCI scope.** That is the entire reason to use Shopify.

### 5.2 Python specifics

The Storefront API is GraphQL over HTTPS — `httpx` plus `gql`, or raw POST requests. 
There is no meaningful SDK gap because there's barely anything to SDK.

Two things to get right:

- **Two tokens, two scopes.** The Storefront API public access token is safe in the browser (scoped to public catalog data). The Admin API token is server-side only and must never appear in the PWA bundle. Storefront token → storefront. Admin token → ERP sync.
- **Cart state lives in Shopify.** The cart is a Shopify object with an ID. Store the cart ID in a cookie and hydrate from the API. Do not build a parallel cart in Postgres — you'll desync from checkout.

For the PWA: FastAPI or Django with server-rendered HTML plus HTMX gives fast, SEO-friendly pages; add the service worker for offline/installability on top. Plan for the fact that checkout is a redirect off your domain — the service worker must not intercept it, and analytics needs cross-domain handling.

### 5.3 The subscriber portal

The piece that doesn't fit cleanly into "my Python app owns the frontend." 

Three options:
1. Shopify's Customer Accounts surface — constrained, minimal work
2. Your subscription app's hosted portal — branded, but theirs
3. **Your own portal in Python against the app's API** — Recharge, Loop, and Smartrr all expose one

Option 3 is the right answer here. 
Roughly a couple of weeks of work, and it puts the highest-leverage retention surface under your control.

---

## 6. Shopify platform reference

### 6.1 Liquid

Shopify's templating language (written in Ruby, open-source), used for classic themes. 
Deliberately logic-light: filters, loops, conditionals, no arbitrary code execution. 
Modern themes pair Liquid with JSON templates, sections and blocks, and metafields/metaobjects for custom data modelling. 
Familiar if you've written Jinja or Twig.

**Relevant to you only if you use Shopify-hosted themes.** 
Going headless, you skip Liquid entirely.

### 6.2 GraphQL APIs

| API | Access | Use |
|---|---|---|
| **Storefront API** | Public token, browser-safe | Catalog reads, cart mutations — what a headless frontend uses |
| **Admin API** | Private token, server-side only | Products, orders, customers, inventory, fulfilment |

The REST Admin API has been legacy since 1 October 2024, and since 1 April 2025 all new public apps must be built exclusively on the GraphQL Admin API. 
Existing REST endpoints still respond, but REST is in maintenance mode and receives no new capabilities. 
**Do not start anything new on REST.**

Practical notes:
- GraphQL Admin uses a **query-cost budget**, not requests-per-second
- **Bulk Operations API** for anything over ~250 records
- Quarterly API versions with limited support windows

### 6.3 Shopify Functions

Server-side logic executed inside Shopify's own infrastructure — discounts, shipping rates, payment method customisation, cart transforms. 
Runs in a WebAssembly sandbox and deploys as an app.

Any language that compiles to Wasm is supported (Rust, Zig, TinyGo), subject to binary-size and performance limits. 
JavaScript/TypeScript is what most people use; Rust is the performance option. 
Functions replaced the old Ruby-based Shopify Scripts.

**Relevant to you** if you need build-a-box via Cart Transform Functions.

### 6.4 Checkout Extensibility

The sanctioned way to customise checkout now that `checkout.liquid` is retired. 

Three parts:
- **Checkout UI Extensions** — React components in defined slots
- **Functions** — tamper-proof server-side logic
- **Branding API** — colours, typography, button styles, corner radii

Structural layout changes remain impossible. **This is the constraint to evaluate hardest, because it's the one you cannot code around.**

### 6.5 Tooling

Shopify CLI · app templates for React Router/Remix and Node · Polaris design system · App Bridge for embedded admin UIs · Web Pixels API for sandboxed analytics · theme app extensions · Shopify Flow for no-code automation.

### 6.6 Hydrogen (optional)

Shopify's own headless framework: React Router v7 (adopted early 2025 as Remix's successor), Vite build toolchain, streaming SSR, granular caching at the response/page/component level, deployed to Oxygen edge hosting (free on paid plans).

**You do not need this.** The Storefront API is plain GraphQL — any stack works, including Python. 
Hydrogen is listed here only so it's clear it's optional rather than required.

### 6.7 What cannot be Python

Your storefront can be anything. 

Anything running *inside* Shopify cannot be Python:
| Surface | Language |
|---|---|
| Functions (cart transform, discounts, shipping) | Rust or JS → Wasm |
| Checkout UI Extensions | React |
| Customer Account UI Extensions | React |
| Themes (if used at all) | Liquid |

Not a dealbreaker, but the stack won't be single-language. 
Expect a small Rust or TypeScript project living alongside the Python app.

---

## 7. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Shopify Payments unavailable in your country | **Blocking** | Verify eligibility before writing any code — native subscriptions require a vaulting-capable gateway |
| ERP scope creep consumes the team | High | Build only curation/forecasting/analytics; buy inventory, shipping, accounting |
| Sync-layer drift between ERP and Shopify | High | Single owner for inventory truth; nightly reconciliation with alerting |
| Duplicate customer records across systems | High | Decide the owning system before launch, not after |
| Subscription vendor consolidation | Medium | Prefer vendors with clean data export; avoid deep proprietary coupling |
| Checkout structural limits block a needed flow | Medium | Prototype the checkout experience early, before committing |
| Quarterly API version churn | Low | Budget a few days per year as standing maintenance |
| Bus factor on custom ERP | Medium | Documentation and test coverage from day one |

---

## 8. Decisions still open

These three determine whether the recommended architecture holds:
1. **Are boxes fixed-contents or curated per subscriber?**
   Fixed → headless Shopify, very little to build. Personalised → you're writing a real allocation engine regardless, and the build-vs-buy line moves closer to custom.
2. **Who owns inventory truth — ERP or Shopify?**
   If the ERP owns it and Shopify mirrors, the architecture is clean; ship it. If you find yourself wanting Shopify to own inventory because the ERP isn't ready, that's a signal the ERP is further from done than "finishing up" implies. Worth being blunt about before committing the storefront architecture to it.
3. **Who owns the customer record?**
   Orders flow into both systems. Pick a winner up front or spend a year reconciling duplicate customers by email — the most common way this architecture goes bad.

---

## 9. Anti-patterns to avoid

- **Splitting one-time purchases onto Shopify and subscriptions onto your own Stripe setup.** Two customer records, two order histories, two fulfilment pipelines, and a support team that hates you. Pick one system of record.
- **Building a parallel cart in your own database.** Desyncs from checkout.
- **Building a general ledger.** Use QuickBooks or Xero.
- **Starting new integrations on the REST Admin API.**
- **Shipping the Admin API token in the frontend bundle.**
- **Building a general-purpose ERP** rather than the box-business-specific parts.

---

## 10. Suggested sequence

1. Verify Shopify Payments eligibility and subscription support in your market — **gate on this**
2. Decide inventory owner and customer-record owner
3. Prototype the checkout + subscription flow end-to-end on a dev store, with a real selling plan and a real card
4. Pick the subscription app (Loop / Recharge / Smartrr) on fee structure at your projected volume, plus API quality for a custom portal
5. Build the Python storefront against the Storefront API
6. Build the ERP ↔ Admin API sync with reconciliation from day one
7. Build the custom subscriber portal against the subscription app's API
8. Add Cart Transform Functions only if build-a-box requires them
