# Business Control

A local-first PWA for running the food brand: customer & distributor ordering,
employee time clock, A/B-tested storefront content, influencer affiliate links,
regional analytics with funnel drop-off detection, truck route planning, store
inventory, and regional sales outreach.

Python (FastAPI + SQLite) backend, vanilla-JS PWA frontend. No cloud, no
external services — everything lives in this folder.

## Quick start

1. Double-click **`command_utilities/Install Business Control.command`**
   (builds a private `.venv`, creates + seeds the database, prints your
   **admin key**).
2. Double-click **`command_utilities/Start Business Control.command`** —
   opens http://127.0.0.1:8860.
3. Sign in with any name and paste the admin key to unlock the admin tabs.
   The admin key is also in `data/config.json`.

Stop with **`Stop Business Control.command`**. Desktop app icon via
**`Install App Icon.command`** (or answer "y" during install). For installing
the PWA from a phone, use **`Start Business Control (HTTPS).command`** and
accept the self-signed-cert warning.

Seeded demo employee PINs: `1111` `2222` `3333` `4444` (Time Clock tab).
Demo affiliate link: `http://127.0.0.1:8860/r/ava01`.

## Layout

```
src/backend/      FastAPI app
  main.py         all API endpoints + static file serving
  config.py       paths, defaults, admin key (data/config.json)
  db.py           SQLite schema
  auth.py         name-based login, bearer tokens, admin key
  abtest.py       variant auto-generation, sticky assignment, z-test winner
  analytics.py    regional rollups, funnel + drop-off, engagement fall-off
  logistics.py    haversine, nearest-neighbor + 2-opt route planner
src/frontend/     PWA (index.html, app.js, styles.css, sw.js, manifest)
scripts/          launch.py, seed.py, make_icons.py
tools/            make_launcher.py (Desktop .app builder)
command_utilities/  double-click launchers (install/start/stop/tests/uninstall)
tests/            script-style smoke test (Run Tests.command)
data/             SQLite DB + config.json (created at install; gitignored-ish)
```

Full guide to accounts, roles (including founders/owners), sign-in, and the
admin view: **[docs/USERS.md](docs/USERS.md)**.

## Who sees what

| role        | tabs |
|-------------|------|
| signed out  | Shop (browse), Time Clock (PIN punch) |
| customer    | Shop (retail prices), Orders, Affiliates |
| distributor | Shop (case/wholesale prices), Orders, Inventory |
| influencer  | Shop, Orders, Affiliates (personal link + earnings) |
| employee    | + Inventory, Routes, Outreach |
| admin       | everything + Experiments, Analytics, Admin |

## Feature notes

- **A/B testing** — "Auto-generate experiment" picks your top-selling product
  and creates headline/CTA/theme variants. Visitors are hash-bucketed (sticky).
  Results show per-variant conversion with a two-proportion z-test; a winner is
  suggested once every variant has ≥30 exposures (`ab_min_exposures`).
- **Funnel** — the storefront logs visit → view_product → add_to_cart →
  checkout → purchase. Analytics shows per-step counts, flags the biggest
  drop-off, and alerts when a week's engagement falls below 75% of the prior
  week (`falloff_ratio`), overall and per step.
- **Routes** — "Plan" takes every active store in a region (or explicit store
  ids via the API), puts a distributor DC first as depot, and orders stops via
  nearest-neighbor + 2-opt on haversine distance. Stops can be checked off as
  delivered; the map is drawn from store coordinates.
- **Affiliates** — influencers get `/r/<code>` links; clicks are counted, the
  code rides the visitor's browser, and orders accrue a 10% commission
  (`default_commission_bps`).
- **Time clock** — PIN-only punch (no login needed) so a store tablet works;
  admins see the full timesheet, employees see their own shifts.
- **Affiliate feed** — Feed tab where affiliates post what they're saying about
  the brand. A pasted link gets a preview pulled live from the platform's
  public oEmbed endpoint (YouTube, TikTok, X — no API keys) with an OpenGraph
  fallback for any other site; fetch failures still store the post, just
  without the card. Each post shows the orders that affiliate's code drove in
  the last 7 days. Admins can delete posts; every signed-in user can read.

- **QR codes** — the sign-in screen shows an "open on your phone" QR (LAN
  address); admins can issue single-use, 10-minute sign-in QRs per user from
  Admin → All users; affiliates get a QR of their referral link for packaging
  and stories.
- **Analytics pixels** — Admin → Analytics pixels takes Google Analytics 4,
  Meta (covers Facebook + Instagram), and TikTok pixel IDs. The storefront
  forwards the funnel (view_item / add_to_cart / begin_checkout / purchase with
  order value) to every configured platform. Empty = that pixel never loads.
- **Scan tab** — in-app camera QR scanner (BarcodeDetector; manual entry
  fallback for iPhone Safari). Drivers scan the truck-cab QR (printed from
  Routes) to check in and pull up that truck's route; sign-in and promo QRs
  scan too. Phone cameras require the HTTPS start command.
- **Route times & auto-coverage** — every route carries drive-time and
  per-stop ETAs (`route_avg_kmh`, `stop_service_min`). "Auto-plan coverage"
  regenerates one optimized route per region over all its stores, and adding a
  store automatically re-plans that region (`auto_routes_on_store_add`).
- **Promotions & events** — create scannable promos (product, % off) and
  in-person events (location, start time, video feed). Each gets a QR whose
  landing page pitches the offer and walks the customer through installing the
  PWA; scans are counted. Employees clock into events from the Time Clock, and
  events show staffed hours.
- **P&L** — Analytics and HQ show a 30-day P&L: revenue → COGS → gross →
  commissions, labor (from the time clock), trucking (from routes) → net.
  Assumptions (`cogs_bps`, `hourly_wage_cents`, `cost_per_km_cents`) live in
  config.
- **HQ (run the business)** — the owners' map: every store plotted, each
  region scored bronze/silver/gold on market penetration with 30-day revenue
  momentum, and a playbook of one-tap actions (launch an A/B test, plan a
  coverage route, work open prospects) that execute for real.
- **Notifications** — bell in the top bar with an unread badge, polled every
  45s. Pushed on real events (orders in, order status for the customer, truck
  check-ins, new affiliates, accounts newly stocked, experiment results) and
  swept from data conditions (low stock, engagement fall-off, an experiment
  ready to call) with dedup keys so nothing repeats. Grants browser desktop
  notifications if you allow them when first opening the bell.
- **Achievements** — 15 company milestones computed from real data (first
  sale, $1k/$10k revenue, experiment winners, affiliate milestones, route km,
  shelf space, golden territory…). Locked ones show live progress in HQ;
  unlocks persist and announce themselves via notification.
- **Phone push (Web Push)** — bell panel → "📲 enable push" subscribes the
  device through its platform push service (VAPID keys auto-generated into
  `data/`; needs internet to deliver). Notifications and offline chat messages
  then arrive even with the app closed. iPhone requires the PWA installed to
  the Home Screen (iOS 16.4+) and the HTTPS start command.
- **Chat, calls & video** — Chat tab with a Team room for all staff, staff
  DMs, and a Support conversation per customer (their customer-service line).
  Real-time over WebSocket with REST fallback; offline members get a push.
  📞/📹 buttons place WebRTC voice/video calls (accept/decline ring, hang-up);
  peer-to-peer, so on-LAN calls need no external service. Camera/mic require
  HTTPS on phones.
- **Email marketing** — Admin → Email marketing takes SMTP settings (empty
  host = dry mode: everything logs, nothing sends). Automated playbooks run on
  the sweep: abandoned-cart (added to cart 1–48h ago, didn't buy, max
  once/week) and win-back (no order in 30 days, once/30d), deduped in
  email_log. "✉️ blast" on any promo emails it to every customer with an
  address, once each. Customers supply email at sign-in.

- **Real commerce** — customer orders require a shipping address and carry
  tax (8% default) + flat shipping (free over $40) + a payment status.
  Customers pay on delivery, distributors ship on terms, and a
  `stripe_secret_key` in config turns on hosted Stripe Checkout (verified
  server-side on return; admins can always "mark paid"). Shipping an order
  consumes stock at the best-stocked store in region; delivering a route stop
  restocks that store to par — inventory, routes, and P&L stay one system.
- **Passwords** — optional per account: the login password field adopts a
  password on first supply, then requires it. `require_passwords: true`
  enforces them (do this before going public). Admins can reset from All
  users.
- **Backups** — `Back Up Data.command` snapshots the DB (WAL-safe) + config +
  keys into `data/backups/` (30 kept); `Restore Data.command` restores the
  newest, keeping the current state aside.
- **Going public** — see `docs/DEPLOY.md` (VPS + Caddy TLS + systemd);
  `public_base_url` in config flips every QR, sign-in link, email, and Stripe
  return to the public domain.

## Config (`data/config.json`)

`port` (8860), `regions`, `default_commission_bps`, `ab_min_exposures`,
`ab_significance_z`, `falloff_ratio`, `brand_name`, `admin_key`,
`qr_login_ttl_sec`, `tracking` (pixel IDs — also editable in the Admin tab).

## Tests

`Run Tests.command`, or:

```sh
./.venv/bin/python3 tests/test_smoke.py
```
