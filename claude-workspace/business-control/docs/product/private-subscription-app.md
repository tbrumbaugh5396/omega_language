# The private subscription app: architecting Shopify without Recharge

Companion to `ecommerce-architecture-decision.md`. 
Decision recorded here:
**prototype the private-app route first**; rent Recharge/Loop only if our dunning measurably underperforms at real volume.

## The core clarification

You never need a separate payment *processor* — Shopify Payments charges the cards either way. 
The build-vs-rent question is only about the **subscription app layer**: the thing that decides *when* to charge each contract and what
to do when a charge fails. Shopify's native subscription APIs are open to any app, including a private one. 

Division of labor:
| Concern | Owner |
|---|---|
| Card vault, network tokens / card updater, SCA/3DS | Shopify Payments |
| Selling plans, subscription contracts, billing attempts | Shopify APIs |
| Scheduling (bill day), retries/dunning, cycle counts | **business-control** |
| Curation, allocation, cutoffs, portal rules | **business-control** |

## The API primitives

1. `sellingPlanGroupCreate` — defines "monthly box, 10% off", attached to products. Buying with a `sellingPlanId` makes checkout vault the card and create a `SubscriptionContract`.
2. `subscriptionContracts(query: "status:ACTIVE")` — the contract book.
3. `subscriptionBillingAttemptCreate(contractId, idempotencyKey)` — "charge this contract now." Shopify does the charging; webhooks report outcomes: `subscription_billing_attempts/success` and `/failure` (with decline code).

That's the whole surface. 
The app we own is: a bill-run loop + outcome webhooks + a retry schedule + the cycle calendar (already built in `cycles.py`).

## What's implemented (prototype, `shopify_sub.py`)

- **Status/ping** — `GET /api/admin/shopify/status`; mock mode when no store is configured (3 fake contracts, 2 active) so the pipeline runs untested.
- **Selling plan setup** — `POST /api/admin/shopify/selling-plan`.
- **Bill run** — `POST /api/admin/shopify/bill-run {cycle_month}`: walks
  active contracts, fires billing attempts **exactly once per contract per cycle** (`sub_billing` unique constraint makes reruns safe), records outcomes, and syncs the cycle's `billed_count` automatically.
- **Webhook receiver** — `POST /webhooks/shopify`, HMAC-verified (`shopify.webhook_secret`), flips pending attempts to success/failed and refreshes cycle counts. Failure payloads carry the decline code — the input for dunning.
- 9 tests cover mock mode, idempotency, count sync, and HMAC handling.

## What's deliberately NOT built yet

- **Dunning retries.** v1 plan: retry failed attempts on day +2, +4 (inside the dunning window from `cycles.py`), hard-decline codes never retried. This slots into the notification sweep exactly like the email playbooks.
- **The subscriber portal** (skip/swap/pause) — reads `changes_open` from `/api/cycles/current`, writes contract changes via Admin API.
- Prepaid plans, proration. Rent-a-vendor territory if ever needed.

## Dev-store setup (requires your Shopify account — manual steps)

1. Create a free Shopify **Partner account** → create a **development
   store**. Enable Shopify Payments **test mode** on it.
2. Store admin → Settings → Apps → **Develop apps** → create app
   "business-control". Grant Admin API scopes:
   `read_products, write_products, read_customers, read_orders,
   write_own_subscription_contracts, read_own_subscription_contracts`.
3. Install the app to the store; copy the **Admin API access token** into `data/config.json` → `shopify.admin_token` + set `shop_domain`.
4. Settings → Notifications → Webhooks: point `subscription_billing_attempts/*` at `https://<public_base_url>/webhooks/shopify`; copy the signing secret into `shopify.webhook_secret`. (Webhooks need the deployed HTTPS URL — or a tunnel during development.)
5. In business-control Admin: check Shopify status → create the selling plan → attach it to a product in the store admin → place a test subscription order with a test card → run a bill run against the cycle.

## Risks / notes

- The subscription mutations require the store to use **Shopify Payments** (or a vaulting-capable gateway) — the doc's blocking risk; verify first.
- `write_own_subscription_contracts` means an app can only bill contracts it created — buy through *our* selling plan, not another app's.
- Quarterly API versions: `shopify.api_version` is config, bump ~yearly.

## Oxygen / "the edge" — what's actually distributed

Two different things, often conflated:

- **Shopify's APIs** (Storefront API especially) are served from Shopify's own globally distributed infrastructure **no matter what you build with** — a Python storefront gets the same fast, CDN-backed API responses as a Hydrogen one. Checkout likewise always runs on Shopify's infra.
- **Oxygen** is *frontend* edge hosting: it runs your **Hydrogen app's SSR code** at edge locations. It is only relevant if your storefront is Hydrogen. Our storefront is Python on our own server — our HTML origin is our VPS, and the "edge" we get from Shopify is the API/checkout side only.

So: API distribution is universal and free; frontend distribution is opt-in via Oxygen (Hydrogen-only) or achievable independently with any CDN in front of our own app.
