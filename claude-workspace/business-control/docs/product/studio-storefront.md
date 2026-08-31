# The studio's own storefront

**Written August 2026.** Business Control sells Business Control from an
install of Business Control. This is what that shop is, and — more usefully
— what had to leave the codebase for it to be possible.

## What it is

`localhost:8860` (the studio tenant) serves:

| | |
|---|---|
| **Home** | Hero, the numbers, three reasons, the buyable plans, how the bill is made of two parts, the full capability menu, the care table, FAQ, price-book signup |
| **`/p/pricing`** | The menu again in full, the worked bundle examples, care, and the build ladder |
| **`/p/how-it-works`** | The six stages of an engagement, each with its gate |
| **`/partners/…`** | Four ways to work with us — build, migrate, white-label, care — each opening a lead on the sales board through the enquiry rail |

Seven products are buyable: the three plans, the three care plans, and
Guided setup. The larger builds are quoted after discovery; an add-to-cart
button on a $40,000 engagement is a lie a shop does not recover from.

## Every number comes from the price book

`src/storefront/backend/pricebook.py` parses
[price-book.md](price-book.md) — capabilities and bands, Platform Core,
tiers, care plans, the build ladder, the bundle examples. `scripts/
seed_studio.py` builds the shop from it and **retypes nothing**. A table the
parser cannot read raises rather than quietly selling the wrong figure.

```bash
python scripts/seed_studio.py --force
```

Change a price in the book, re-run that, and the shop agrees with the quote
bench, the deck and the client menu — because all four are held to one
table.

Without `--force` it refuses once the shop has products, so it cannot
overwrite copy an operator has edited by hand.

## Plans bill every month

`store_subscriptions` now carries two kinds of row, and `interval` is what
tells them apart:

- **A box** (`interval = ''`) is a physical thing, curated and shipped on a
  cycle. Its verbs are skip and unskip, and they race the curation cutoff.
- **A plan** (`interval = 'month'`) is money on a clock. No cycle, no
  shipping; pause, resume and cancel.

A product becomes a plan by setting `store_product_meta.billing` to
`month`. Everything else follows from that one flag: the card shows
`$349/mo` and a **Start** button instead of Add, the one-off cart refuses
it outright, and checkout opens in Stripe's **subscription** mode with a
recurring price.

Three things worth stating plainly, because each is a way this rail can go
quietly wrong:

- **The price is locked on the row at signup.** The price book says
  grandfather existing clients; a column is the only way that survives a
  repricing. The account panel and the MRR figure both read the agreed
  price, never today's list price.
- **Cancelling cancels at the processor.** A status column saying
  "cancelled" while Stripe keeps charging is the worst bug this rail can
  have, so if Stripe refuses, nothing changes here either and the two still
  agree. Cancellation is at period end — they paid for this month.
- **The subscription id is read back from Stripe**, never taken from the
  return URL, which is a thing anybody can type.

**With no Stripe key configured the plan still starts**, marked `invoice`,
and says so. That is how most of these are actually sold and it is not an
error state. Ops → Admin → *Plans — who is on what* lists everyone, the
MRR, and how many are being billed by hand.

## What left the codebase to get here

The studio storefront looked like a drinks brand because a drinks brand's
voice was compiled into the product. Each of these is now the tenant's own
data, with the shipped value as the default:

| Was, in code | Now |
|---|---|
| Section defaults: L-theanine, "Shop your Zen", "100,000+ Zen customers" | Neutral scaffolding — what a *fresh* tenant of any kind should open on. A shared default that invents a customer count puts a number on a shop in the merchant's name |
| `"Shop your Zen"` in the shared storefront script | `ui_strings.shop_cta`, per tenant |
| `"Take 10% off your first calm."` in the shell | `ui_strings.offer_title`, per tenant |
| A `/partners/work` link hard-coded in the side menu | Gone — the partner pages already list themselves from data |
| `PATHS`: five landing pages of one business's copy, on everybody's site | `store_meta.partner_pages`, same shape, same renderer |
| Three font families hard-coded in the shell | `font_link(theme)` — the faces the theme asks for, and no others |
| The wordmark face, fixed at Quicksand | `theme.wordmark_font` |
| A drawn drinks can as every product's stand-in art | `theme.art`: `can` or `card`, read by both the grid and the server-rendered product page from one switch |
| `ZJ-` on every ticket reference | Brand initials, or `support_contact.ref_prefix` — zenjoy pins `ZJ` |
| "A question about the drinks" ticket topic | Neutral label; `support_contact.topics` renames per tenant |
| "breathe in, check out." over the cart | `ui_strings.cart_tag`, per tenant |
| "Free shipping over $40" in the announce default and cart note | Empty defaults (`ui_strings.cart_note`); an invented policy is worse than a blank, and an empty announce bar hides itself |

**The business phone is one saved value.** Store admin → Support holds the
number (point it at a VoIP service and edit it there when it changes), the
hours, and the support email; the support hub, the storefront footer and
the Organization markup search engines read all follow it. A footer toggle
exists for merchants who want it only in the hub. Saving the phone used to
silently erase the email — the form omitted a field the server writes
whole; fixed and pinned by a test.

ZenJoy's install carries its own values for all of these, written by
`scripts/split_tenants.py`, so nothing its storefront can see changed.

## Three bugs the work surfaced

- **The section back-fill ran forever.** It claimed to place the carousel
  "once", but its test was "is this type absent?" — so a merchant who
  deleted it found it back on the next restart, every restart. It now
  records what it has applied in `store_meta.home_backfill`.
- **`richtext` escaped its own markup.** A field labelled richtext, helped
  as "simple formatting allowed", escaped every tag it invited. It now
  allows a short whitelist; `<script>` and `javascript:` links are still
  escaped, and the deliberate escape hatch is the custom-code section.
- **The hero showed whatever sorted first** — for a shop selling plans,
  that was the cheapest support plan, in grey. A product can now be flagged
  `featured`, and the hero takes it.

## The one it did not fix

At 357 px the top bar overflowed once the wordmark was two words. The
wordmark now scales and the bar gives up padding first. A name longer than
"business control" will find the same edge again; the honest fix is a
wordmark that knows how to abbreviate, and it is not built.
