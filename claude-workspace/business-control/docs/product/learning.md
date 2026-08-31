# Learning — the lingua-portal port

The Learning capability ($50, Operations group) is lingua-portal ported onto
this platform. The source was a language-school portal in two processes (a
marketing site and a school portal); here the same school lands on the four
surfaces every tenant already has:

| Layer | lingua-portal had | on business-control |
| --- | --- | --- |
| Public storefront | site.py marketing pages, public registration form | `/` (courses shape) + `/learn` catalogue + the apply form — submitting grants nothing; approval creates the account and the seat |
| Frontend admin | operator console pages | `/admin` — pages, theme, sections, media (richer than the source had) |
| Behind the sign-in | server.py portal: students, teachers, directors | students on `/learn` (lessons, quizzes, progress, check-in, badges, attendance standing); teachers and directors on the ops **Learning** tab (authoring, live roster, grading queue) |
| ERP / CRM | payroll derivation, registrations queue, audit | `/ops` — derived teaching pay with the approve/hold/paid overlay, the applications queue, and the platform's own audit log, notifications, orders and staff |

## What moved verbatim

Two pure modules came over whole, with their tests restated in the suite:

- **`erp/backend/assessment.py`** — grading. Accents/case/punctuation
  forgiven; multi-choice partial credit floored at zero; `is_final`
  load-bearing; a learner never sees a provisional score, and never
  receives the answer key (stripped server-side).
- **`erp/backend/attendance.py`** — the class-session loop. One open
  session per course; self check-in says "I'm here" and the rules classify
  it; a teacher's mark records its actor and beats self-service; closing
  writes system-marked absents so "no row" is never ambiguous. **Payroll is
  a derivation, not a ledger** — pay computes from closed sessions
  (minimum floor, round-up blocks, both favouring the teacher);
  administrators own only the approve/hold/paid overlay, and held pay stays
  visible rather than silently deducted.

## What was re-homed

- `classes.py` → `erp/backend/classroom.py` (sessions, check-ins, roster,
  pay rates, payroll).
- `lessons.py`/`quizzes.py`/`registration.py`/`achievements.py` →
  `erp/backend/learning.py` (the draft/published boundary, the
  enrolled-only visibility rule, update-don't-duplicate applications,
  badges re-derived from data on every award call).
- The learner surface → `storefront/backend/learn.py`, behind the tenant's
  Learning entitlement (revoked = 404 + pruned nav, like every capability).

## What this platform adds that the source never had

- **Checkout as admissions**: a course may name a product
  (`courses.product_id`); buying it enrols the buyer, and the seat records
  which order opened it. The source had no payment rail at all.
- Multi-tenancy, backups, entitlements, the site editor, notifications and
  audit come from the platform — the source's ~3,100 lines of
  tenancy/auth/audit/licensing infrastructure were discarded, not ported.

## Role mapping

The source's seven-role matrix (director/staff/teacher/volunteer/board/
donor/student) maps onto the platform's users: admins play director and
staff; a teacher is the user a course names (`courses.teacher_id`); a
student is anyone **enrolled** — enrolment, not role, is what opens
published lessons and check-in. Board/donor visibility rules wait for a
governance need that hasn't arrived here.

## The community (ported)

The learner-to-learner social layer lives in `erp/backend/community.py` and
the People tab on `/learn`, with the source's three load-bearing rules
intact:

- **Messaging requires a mutual contact, enforced on SEND** — anyone can
  find people and ask; nobody talks until the other side says yes. The one
  keyhole is per-person open DMs, off by default. Blocks sever the contact
  edge at the same moment; ghost mode is one-directional invisibility with
  messaging paused both ways, and the friendship resumes intact on unghost.
- **Privacy is the person's own dial, applied in one place** —
  everyone / first-name-and-initial / my-classes-only / contacts / nobody.
  Staff and teachers always get full records (a roster cannot run on
  initials); everyone else gets the person's choice, and "hidden" is
  indistinguishable from "does not exist".
- **Message bodies never reach staff** — not even traffic is audit-logged.
  The release valve is the conduct report: a party to a conversation can
  hand ONE message to the office, snapshotted at that moment so the
  evidence outlives the sender. The queue and resolution live on the ops
  Learning tab.

Adapted in the move: the community is scoped to the school (enrolled,
teaching, or administering — never the shop's whole customer file), and the
source's people-photos and QR identity cards have no counterpart here yet.

## Live video (ported)

Every class session carries a video room from the moment it opens; the
learner's "Class is in session" banner and the teacher's roster join the
same call. DMs can carry calls too. The client is the source's
peer-to-peer mesh (`storefront/frontend/rtc-mesh.js`, used by BOTH the
/learn page and the ops roster — one client, not two): perfect-negotiation
glare handling, a per-peer bitrate cap that shrinks as the room grows, and
the graceful-media ladder — no camera means you join to watch and listen,
told honestly, never refused. Signaling is HTTP-polled mailboxes
(`/api/learn/rtc/*`), keyed by tenant so two schools sharing a process
never share a room; the server relays SDP/ICE and never touches media.
TURN for symmetric-NAT deployments configures via `turn_url` /
`turn_user` / `turn_pass`. The source's SFU transport (WHIP/WHEP) is not
ported — it needs a media server nobody here runs yet; the mesh carries a
class of up to 12.

## Still waiting from the source

Audited against the source's full endpoint surface. Ported and live:
courses/lessons/quizzes/grading, the class-session loop and derived
payroll, admissions, the social layer, mesh video, notifications. Covered
by the platform's own richer versions (deliberate substitutions, not
gaps): auth and sessions, tenancy and licensing, audit, the admin
console, tuition (course seats are products on the checkout rail), the
seven-role matrix (mapped to admin/teacher/enrolled). Genuinely not yet
ported:

- **Recordings** — speaking/video quiz answers (the grading engine
  understands them; authoring refuses until the capture flow lands),
  teacher audio drills attached to lessons, and class recording (the
  source composited the teacher's received tiles into one stream).
- **The library** — lending desk with derived availability (and the
  bookworm badge that waits on it).
- **Lookup + speech** — the offline glossary/thesaurus with optional
  LibreTranslate/Datamuse, and browser dictation/TTS. Together these are
  the seed of the priced **Voice & translation** capability ($30,
  depends Learning).
- **QR identity** — per-person unguessable QR cards: scan-to-check-in at
  class and scan-as-contact-handshake (the platform has QR scanning
  infrastructure to build on).
- **Data rights** — per-person export, and erasure with a shown plan
  (the community module keeps messages ready to go with their person,
  but nothing calls it yet).
- **The calendar** — the month grid of class sessions.
- **SFU transport** for classes too large for a 12-person mesh.
