# Business Control as SaaS: multi-tenancy + per-feature hosting costs

**Date: August 2026.** Prices marked *(verify)* move frequently — check vendor
pages before modeling revenue on them. Claude API prices are current as of
this writing.

---

## 1. Multi-tenancy architecture

Today: one install = one `data/business_control.db` + one uvicorn. That
constraint is an asset — the cleanest SaaS evolution is **tenant-per-database**:

```
                 ┌──────────────────────── one VPS / node ───────────────────┐
 customer.brandA.app ─┐   ┌──────────┐   ┌───────────────────────────────────┐
 brandB.bizcontrol.app ─┼─▶│ Caddy    │──▶│ uvicorn (FastAPI, shared code)    │
 brandC.bizcontrol.app ─┘  │ on-demand│   │  tenant router: host → tenant_id  │
                           │ TLS      │   │  con cache: tenant → SQLite con   │
                           └──────────┘   │  data/tenants/<id>/app.db         │
                                          │  data/tenants/<id>/uploads/       │
                                          └───────────────┬───────────────────┘
                                          control-plane DB: tenants, plans,
                                          Stripe billing, node assignment
```

Why tenant-per-SQLite-file beats one big Postgres at this stage:

- **Isolation for free** — no `tenant_id` column audit, no cross-tenant leak
  class of bugs; a tenant's DB *is* their export, backup, and GDPR deletion.
- **The code barely changes** — `db.connect()` takes a tenant id; everything
  else (WAL, backup API, migrations loop) already works per-file.
- **Ops scale-out is file copy** — tenants pin to nodes; moving one is
  rsync + DNS. One 4 GB VPS comfortably carries dozens of food-brand-sized
  tenants (each DB is megabytes).
- Revisit Postgres-with-tenant-id only past ~1k tenants or if a single tenant
  outgrows SQLite's single-writer ceiling (a busy brand won't).

Work items (≈ the real multi-tenant build, in order):
1. Control-plane DB + tenant router middleware (host header → tenant id).
2. Per-tenant `connect()`/config; namespace the chat HUB, push subs, and the
   notification sweep loop (iterate tenants).
3. Caddy **on-demand TLS** for custom domains; wildcard for `*.bizcontrol.app`.
4. Stripe Billing subscriptions on the control plane; plan gates per tier
   (the tier→suite map already exists in the deck).
5. Per-tenant backup rotation (existing `backup.py` looped over tenant dirs).

## 2. Per-feature hosting costs at SaaS scale

Baseline: node VPS (4 GB) **$15–24/mo**, carries many tenants. Then per feature:

| Feature | How we ship it | Cost | Notes |
|---|---|---|---|
| Chat / messaging | Built-in (WebSockets + SQLite) | **$0** marginal | Already multi-user; just namespace per tenant |
| Web push | Built-in (VAPID) | **$0** | Browser push services are free |
| 1:1 voice/video calls | Built-in WebRTC P2P | ~**$0**, but needs TURN | P2P fails on ~10–20% of networks (strict NATs) without a relay |
| — TURN relay | Self-host coturn on the node, or Cloudflare TURN | coturn: **$0–6/mo** + bandwidth (~$1/TB Hetzner); Cloudflare ~**$0.05/GB** *(verify)* | Required before selling calls as a feature |
| Group calls (3+) | Needs an SFU — P2P doesn't scale past 2–3 | LiveKit Cloud ≈ **$0.5–1 / 1,000 participant-min**; Daily ≈ $0.004/participant-min; self-host LiveKit OSS ≈ **$15–25/mo** per node *(verify all)* | Twilio Video is discontinued — don't plan on it |
| Customer support suite | Built-in (support convs, chat, calls) | **$0** | vs Intercom ~$39–99/seat/mo, Zendesk ~$19–55/seat *(verify)* — a genuine selling point |
| **LLM support chatbot** | Claude API | Haiku 4.5: **$1 in / $5 out per MTok**. Typical turn (~1.5k in w/ cached catalog prompt, ~300 out) ≈ **$0.002–0.004**; 1,000 convos/mo ≈ **$3–10/tenant** | Prompt-cache the product catalog/system prompt (reads ~0.1×); Sonnet 5 ($3/$15; intro $2/$10 through 2026-08-31) for an escalation tier; Opus 5 ($5/$25) only for owner-facing analysis. Batches −50% for async jobs (nightly summaries) |
| Microphone / voice interface | STT + LLM + TTS pipeline | STT: Deepgram ≈ $0.004–0.008/min, Whisper API ≈ $0.006/min; TTS: OpenAI ≈ $0.015/1k chars, ElevenLabs ≈ $0.06–0.30/1k chars *(verify)*. Blended voice-assistant cost ≈ **$0.01–0.05/min** + LLM | Browser `SpeechRecognition` is $0 but Chrome-quality only — fine for kiosk commands, not for a product voice bot |
| Email | SES | **$0.10 / 1,000 sends** | Postmark ~$15/mo if you want a dashboard |
| SMS (optional add-on) | Twilio | ~$0.008/msg + $1.15/mo per number *(verify)* | Sell at cost-plus as an add-on, like email volume |
| Offsite backups | Backblaze B2 / S3 | ~**$6/TB/mo** | Tenant DBs are tiny; ~$1–5 total for a long time |
| Payments | Shopify/Stripe rails | % pass-through | Not an infra cost to us |

## 3. What this does to margins

A Pro-tier tenant ($149/mo) consuming realistically — chatbot on Haiku
(~$5), share of node ($2–3), TURN bandwidth (<$1), email ($1), backups
(<$1) — costs **≈ $8–12/mo** to serve → **~92% gross margin**, consistent
with the deck. The two features that can silently eat that margin:

1. **Group video** — per-participant-minute SFU pricing scales with usage,
   not tenants. Meter it (include N minutes per tier, overage at cost-plus)
   or keep group calls a Scale-tier feature.
2. **Voice interface** — $0.01–0.05/min sounds small until a kiosk runs it
   all day. Same answer: metered add-on, not unlimited.

Rule: anything priced per-minute or per-message by a vendor becomes a
**metered add-on** in our pricing; only flat-cost features go into the flat
tiers. That keeps every tier's serving cost bounded.

## 4. Chatbot architecture note (when we build it)

Support bot = Claude API + tool use against our own API: tools for
`order_status(order_id)`, `product_info`, `subscription_state`,
`escalate_to_human` (creates a support conv — already built). Haiku 4.5 as
the default model, cached system prompt carrying brand voice + policies;
escalation is the existing chat, so the human handoff costs nothing extra.
