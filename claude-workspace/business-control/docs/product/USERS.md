# Users, accounts, and sign-in

Everything about who can use Business Control, how accounts are created, and what each kind of user sees.
The app is local-first: accounts live in your own SQLite database (`data/business_control.db`), and there are no passwords or external identity providers by design — access to the admin side is guarded by the **admin key** instead.

## The three front doors (URL topology)

One server, three surfaces — all sharing the same accounts:

| URL | Surface | Who it's for |
|---|---|---|
| `/` | **Customer storefront** | shoppers: cart, checkout, 👤 account & monthly boxes, 💬 support chat, 📦 order tracking |
| `/admin` | **Store admin** — *and the team's front door* | merchandising: products & variants, media, pages, blog, collections, discounts & gift cards, shipping, reviews, menus/redirects, currency & language, webhooks, API keys, staff & audit |
| `/admin/theme` | **Theme & page editor** | visual section builder with live preview |
| `/ops/` | **ERP / CRM ops app** | the team: orders, routes, time clock, chat, analytics |

**Signing in as staff — one door.** 
The storefront's *Team sign-in →* link goes to `/admin`. 
Sign in there once and you're routed by what you're allowed to do: people who manage the store land in the back office, and people whose
work is operations (drivers, warehouse, event staff) are forwarded straight to `/ops/`. 
The session is shared across all three surfaces, so you never sign in twice, and the back office hides any tab your permissions don't cover.

Storefront shoppers sign in implicitly at checkout (name + email creates or finds their account).

## Signing in / creating an account (ops app)

There is one flow for both: 
the login screen **finds or creates** an account by name.

1. Open the ops app at **`/ops/`** → click **sign in** (top right).
2. Enter a **name** — if no account with that name exists, one is created on the spot; if it exists, you're signed into it.
3. Pick what you are (**customer / distributor / influencer / employee / founder-owner**) and optionally a **region**.
4. Optionally paste the **admin key** — this grants the admin flag and is the only way to claim the founder/owner role.

On success the browser stores a bearer token; you stay signed in until you click *sign out* (or an admin deactivates the account). 

Signing in on another device with the same name resumes the same account.

**QR codes:** the sign-in screen shows an *Open on your phone* QR encoding the server's LAN address — scan it from any phone on the same wifi. 
Admins can additionally issue a **one-time sign-in QR** per user (Admin → All users → QR): the user scans it and lands already signed in. 
Those links are single-use and expire after 10 minutes (`qr_login_ttl_sec`).

**Where is the admin key?** Printed by `Install Business Control.command`, and always available in `data/config.json` under `"admin_key"`.

## The roles

| role | how it's created | what they get |
|---|---|---|
| *(signed out)* | — | Browse the Shop, punch the Time Clock with a PIN |
| **customer** | self-serve at login | Shop at retail prices, own Orders, join the Affiliate program, read/post the Feed |
| **distributor** | self-serve at login | Shop at **wholesale case prices**, own Orders, view Inventory |
| **influencer** | self-serve at login (then "Get my link" on Affiliates) | Personal `/r/<code>` link, click/order/commission stats, post to the Feed |
| **employee** | created by an admin (Admin tab → *Add employee*, assigns the time-clock **PIN**) | Time Clock (PIN punch — no sign-in needed at the tablet), own shifts, Inventory, Routes, Outreach |
| **founder / owner** | login with role *founder/owner* **plus the admin key**, or promoted in Admin → All users | Everything, always admin. The role marks the principals of the business, distinct from staff who were merely granted admin |
| **administrator** | any role + admin key at login, or ticked in Admin → All users | All operational tabs: Experiments, Analytics, Admin, full timesheet, all orders, user management |

Notes:

- **Owner vs admin** — *owner* is a role (who you are); *admin* is a flag (what you may do). Owners always carry the admin flag and it can't be unticked; an employee can be given admin without becoming an owner, and it can be revoked later.
- Nobody can self-assign owner: choosing "founder / owner" at login **without** the correct admin key quietly creates a plain customer account.
- Employees are deliberately *not* self-serve — their PIN is handed out by an admin so the timesheet stays trustworthy.

## Tab access matrix

| tab | signed out | customer | distributor | influencer | employee | admin / owner |
|---|---|---|---|---|---|---|
| Shop | ✓ (browse) | ✓ retail | ✓ wholesale | ✓ | ✓ | ✓ |
| Orders | | ✓ own | ✓ own | ✓ own | ✓ own | ✓ all + status |
| Time Clock | ✓ PIN punch | ✓ | ✓ | ✓ | ✓ + own shifts | ✓ + full timesheet |
| Affiliates | | ✓ | ✓ | ✓ + earnings | ✓ | ✓ + all influencers |
| Feed | | ✓ read | ✓ read | ✓ read/post | ✓ read | ✓ + delete |
| Scan (camera QR) | ✓ | ✓ | ✓ | ✓ | ✓ + truck check-in | ✓ |
| Promos | | | | | ✓ view events | ✓ + create, QRs, scans |
| HQ (game view) | | | | | | ✓ owners/admins |
| Inventory | | | ✓ | | ✓ | ✓ |
| Routes | | | | | ✓ | ✓ |
| Outreach | | | | | ✓ | ✓ |
| Experiments | | | | | | ✓ |
| Analytics | | | | | | ✓ |
| Admin | | | | | | ✓ |

(Feed posting requires having joined the affiliate program, whatever the role; admins can always post.)

## The administrators' / owners' view

Signing in with the admin flag adds four things:

- **Experiments** — launch auto-generated A/B tests, watch conversion rates, stop and crown winners.
- **Analytics** — revenue/orders by region, the sales funnel with drop-off detection, engagement fall-off alerts.
- **Admin** — the operations panel:
  - **All users** — every account: change roles, grant/revoke the admin flag, deactivate accounts (blocks sign-in and PIN punches, keeps history). You cannot edit your own row — a second admin has to, which prevents accidentally locking yourself out or demoting the last admin by mistake.
  - **Add employee** (with PIN), **Add product**, **Add store**,
    **Set inventory**.
  - **Analytics pixels** — paste your Google Analytics 4, Meta (Facebook + Instagram share one Meta pixel), and TikTok pixel IDs; the storefront then reports view_item / add_to_cart / begin_checkout / purchase (with order value) to every configured platform. Empty IDs mean nothing loads.
- Elevated views inside shared tabs — all orders (with status control), the full timesheet, every affiliate's stats, feed moderation.

## Seeded demo accounts

`Install Business Control.command` seeds these for trying things out:

| account | role | sign in with |
|---|---|---|
| Maria Lopez | employee | PIN `1111` (Time Clock) |
| Dev Patel | employee | PIN `2222` |
| Jo Kowalski | employee | PIN `3333` |
| Sam Reyes | employee | PIN `4444` |
| Ava Influencer | influencer | name `Ava Influencer`; affiliate link `/r/ava01` |
| Demo Customer 1…N | customer | name, e.g. `Demo Customer 1` |
| Demo Distributor 0, 7, … | distributor | name |

Your first real act as founder: sign in with your own name, role
**founder / owner**, and the admin key from `data/config.json`.

## Security model (read before going multi-user)

Name-only sign-in means anyone who can reach the server can sign in as any non-admin name they know. 
That's the right trade-off for a single-machine or trusted-LAN tool — the valuables (admin functions, founder role) are all behind the admin key. 
If you later expose this beyond people you trust, that's the moment to add real credentials (passkeys or passwords) — say the word and it
can be layered onto the same accounts.
