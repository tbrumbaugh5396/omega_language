# Engagements: running the B2B client kit from the ERP

**Status: all five phases shipped.** This is the execution
plan for turning the paper kit in
[`docs/business-control-b2b-client/`](../business-control-b2b-client/README.md)
into a module the ERP runs — client records, document generation from the kit's
own templates, signatures, per-client folders, and eventually a client portal.

The guiding decision, same as everywhere else in this codebase: **derive,
don't duplicate.** The markdown kit stays the single source of the templates
and the process; the ERP reads it. The stage of an engagement is derived from
which gates have signatures, never set by hand. The client folder export is
generated from the vault, never maintained alongside it.

---

## What already existed (and is reused, not rebuilt)

| Piece | Where | What it gives us |
|---|---|---|
| Document vault + e-signature | `src/storefront/backend/documents.py` | Hash-sealed ESIGN/eIDAS simple signatures, `/sign/{token}` pages, audit trail, expiry, supersede chains, DocuSign provider slot |
| Governance choke point | `src/storefront/backend/governance.py` | One `PATH_RULES` entry puts the whole module under the `documents` permission |
| Shared auth | ERP and store admin share tokens | The ERP frontend calls store-admin APIs directly |
| Dropbox filing of signed docs | `src/erp/backend/integrations.py` | The shape for filing exports off the one laptop |
| The kit itself | `docs/business-control-b2b-client/templates/` | Eleven numbered stages, `[BRACKET]` placeholders, internal-vs-client sides |

## Phase 1 — Client records ✅ shipped

`src/storefront/backend/engagements.py`, mounted under
`/api/store/admin/engagements`, governed by the `documents` permission.

```sql
engagements(id, name, slug UNIQUE, package, value_cents,
            approver_name, approver_email, launch_target,
            staging_url, live_url, notes, status, created_at, updated_at)
engagement_docs(engagement_id, doc_id UNIQUE, stage, side)  -- side: to_client | internal
engagement_log(engagement_id, at, actor, what)
```

- [x] CRUD endpoints; archive via `status`, never delete — links into the
      vault must keep resolving
- [x] "Clients (B2B)" tab in the ERP (Sell group, admin + `documents` grant)
- [x] Detail view: facts, per-stage documents, activity log

## Phase 2 — Documents from the kit ✅ shipped

- [x] Template registry: scan the kit's stage folders at request time — the
      kit on disk is the registry; nothing to keep in sync
- [x] Side derivation: a template whose head says "never send" is `internal`;
      everything else defaults to `to_client`, overridable at generation
- [x] Placeholder extraction: `[BRACKET]` tokens, markdown links and
      checkboxes excluded; one fill per distinct token, filled everywhere it
      appears; unfilled tokens stay bracketed and are counted
- [x] Auto-suggested fills from the engagement record (client, date, value,
      approver) — the proposal and the status board cannot disagree about the
      number because both read the same row
- [x] Generation writes a vault `documents` row (`body` = filled markdown,
      party bound to the client) and links it to the engagement with stage +
      side. Completion continues in the existing Documents tab editor
- [x] Signature requests on generated documents reuse the vault's flow
      unchanged
- [x] Per-client folder export: `data/exports/clients/{slug}/{stage}/{side}/`,
      matching the `clients/_template` convention — body docs as `.md`,
      uploaded files copied, signature certificates as JSON beside signed
      docs, a generated status-board `README.md` at the root
- [x] Zip download, **client bundle by default**: `side=to_client` only. The
      wall from the folder convention is enforced by the query, so the classic
      mistake — zipping the folder and sending the estimate along with it —
      is not possible from this door. `side=all` exists, named `full-archive`
      so nobody mistakes it

## Phase 3 — Gates and derived stage ✅ shipped

- [x] `engagement_gates(engagement_id, gate, doc_id, passed_at, actor, note)`
      — the `note` is the status board's "where it's filed" column, and a
      signature gate passed by hand *requires* it
- [x] Nine gates mirroring the kit: proposal accepted, contract signed,
      **deposit cleared**, requirements signed, art direction signed, round 1,
      round 2, **final invoice paid**, handover accepted. The art direction
      gate only exists once the engagement has brand work — a week website is
      never blocked on a stage it skipped
- [x] Signature gates derive their state from the linked vault document's
      signatures at request time — no copied state, no sync job. Money gates
      are manual confirmations with actor + timestamp, audit-logged. A gate
      only accepts documents filed under its own engagement
- [x] Current stage = the stage of the first open gate, computed on read;
      there is no stage column anywhere to disagree with the signed paper.
      Out-of-order passage warns loudly (in the response, the toast, and the
      activity log) without hard-blocking — taking a deposit on a handshake
      happens, and the tool's job is to make it visible
- [x] Reopening a gate is one delete; the signed evidence stays in the vault
      untouched, and deleting a vault document unlinks any gate resting on it
      so the reopening is visible rather than mysterious
- [x] Sign-page markdown: a no-dependency subset (headings, tables, lists,
      bold/em, links, blockquotes) — a signature attests to what the signer
      was shown, so the shown thing now carries the document's real structure

## Phase 4 — Client portal ✅ shipped

- [x] One revocable tokenized link per engagement (`/engage/{token}`),
      following the supplier-portal precedent. Rotation is revocation with a
      forwarding address: the old link dies the moment a new one exists
- [x] The roadmap rendered from the data: the gate timeline (done / in
      progress / upcoming) reads the same `resolve_gates` the ERP reads;
      dates planned/actual/moved-because from `engagement_dates`; content %
      as a bar; blockers and the week note from the record. Nothing is
      retyped, so it cannot drift from reality — it is the reality
- [x] Shared documents: every portal query filters `side='to_client'` —
      internal documents aren't withheld, they're unreachable. Body docs
      render through the same markdown subset as the sign page; files serve
      through the vault's own storage
- [x] Brand work: boards shown inline (image and PDF documents filed under
      the brand stage — not the storefront media pipeline; the vault already
      stores and serves files, and one storage beats two). The
      direction-review choice is an in-portal form: one consolidated
      response enforced (a second submission is refused), the answer filed
      as a to-client document under the brand stage — the folder convention
      already had a home for the returned form — and brand work existing is
      what wakes the art direction gate
- [x] Pending signature requests surfaced on the roadmap; signing stays on
      `/sign/{token}`
- [x] ERP side: create/copy/rotate/revoke portal controls, content % + week
      note + blockers on the edit form (clearable — "no blockers" is the
      good news), and a dates editor

## Phase 5 — Rhythm and filing ✅ shipped

- [x] The client list is the weekly-rhythm dashboard: stage, content %, when
      the client last looked (portal views stamp `portal_seen_at`), and
      warnings derived server-side so every reader of the API agrees what
      "stale" means — roadmap note older than a week, client hasn't looked
      in a fortnight, N awaiting signature, blocked. Warnings only fire on
      active engagements with a portal; a project without one isn't nagged
      about a link nobody made
- [x] `gate.passed` and `direction.chosen` are events on the same bus as
      `inventory.low`, raised through `fire_webhooks` — the single fan-out,
      so HTTP webhooks, Discord and the integrations all hear them. Slack
      hears both; Trello gets a card only for the direction choice, because
      that one is work (write up the art direction). A gate that passes by a
      signature arrives as `document.signed`, which the bus already carried.
      *Not built:* automatic stall events — there is no scheduler in the
      app, and a stall "event" re-fired on every dashboard load is noise
      wearing an alarm's clothes; staleness lives on the dashboard instead
- [x] Dropbox filing of the export tree via a generic `dropbox_put` on the
      same connection that files signed documents — off-thread, outcome
      logged into the engagement's activity either way, because a cloud
      outage must never fail the local export and a silent non-filing would
      read as filed
- [x] Payment links for the money gates (deposit *and* final invoice) via
      Stripe Checkout — the link is copied to send with the invoice, and
      "Check payment" passes the gate with Stripe named as the actor:
      verified, not vouched for. No key configured → a clear refusal that
      points at manual confirmation, which stays for cheques and transfers

## Honest limits

- The built-in signature is **simple** electronic signature — enforceable for
  ordinary commercial agreements, no verified identity. The `esign` provider
  slot routes to DocuSign when a client demands more.
- One fill per distinct token: `$[X]` means different amounts in different
  places in some templates; fills apply everywhere the token appears. Leave a
  token blank to keep the brackets and finish by hand in the editor — the
  unfilled count is surfaced, and the kit's own rule stands: nothing ships
  with `[BRACKETS]` left.
- The template scan reads `docs/business-control-b2b-client/templates/` from
  the working tree. A deployed install without the docs folder gets an empty
  registry and a clear message, not an error.

## The Scope of Work (added 2026-09-01)

Generated, never blank. **Draft SOW** on an engagement composes the paper
from what the record already knows: deliverables and scale from the quote
(the signed one wins), fees from the published price book, and the
timeline from the engagement's own schedule — so the SOW cannot disagree
with the record it rides on. Identity facts stay as `[TOKENS]` and read
live until signature; the derived tables are baked at drafting, because
the draft is the record's view that day and signing is what turns the
view into a commitment. It files under the agreement stage, edits like
any vault paper, and freezes when signed.

**The schedule speaks even when nobody wrote dates.** Every gate carries
a date labelled with its source — *actual* (the gate closed), *planned*
(the Dates table), or *estimate* (the previous gate's date plus a default
duration, chained from today). The gantt's tracks moved server-side
(`TRACKS` + `schedule_of`/`tracks_of` in engagements.py) so the chart in
ops and the timeline in the SOW read the same fact; estimates are marked
`(est.)` / `?` everywhere they appear, and a written date replaces them
the moment it exists.

**Change orders, not edits.** Once a SOW is signed, Draft SOW offers a
change order instead: a short paper naming the signed SOW it amends
(what changes, the fee delta, the timeline effect), signed the same way.
Amending an unsigned SOW is refused — an open draft just gets edited.
