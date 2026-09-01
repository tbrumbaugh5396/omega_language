# Learning — the lingua-portal port

The Learning capability ($50, Operations group) is lingua-portal ported onto
this platform. The source was a language-school portal in two processes (a
marketing site and a school portal); here the same school lands on the four
surfaces every tenant already has:

| Layer | lingua-portal had | on business-control |
| --- | --- | --- |
| Public storefront | site.py marketing pages, public registration form | `/` (courses shape) + `/learn` catalogue + the apply form — submitting grants nothing; approval creates the account and the seat |
| Frontend admin | operator console pages | `/admin` — pages, theme, sections, media (richer than the source had) |
| Behind the sign-in | server.py portal: students, teachers, directors | students on `/learn` (lessons, quizzes, progress, check-in, badges, attendance standing, and **My record** — the whole standing across courses on `/api/learn/record`, derived on read, with a JSON download, a printable transcript, and a certificate for any completed course; stationery rendered client-side, facts served); teachers and directors on the ops **Learning** tab (authoring, live roster, grading queue) |
| ERP / CRM | payroll derivation, registrations queue, audit | `/ops` — derived teaching pay with the approve/hold/paid overlay, the applications queue, and the platform's own audit log, notifications, orders and staff |

## The seven roles

lingua-portal's role matrix came over as `erp/backend/roles.py` — pure, so
the whole permission table is enumerated in the suite rather than sampled.
Student / Teacher / Volunteer / Administrator-staff / Executive director /
Board member / Donor, mapped onto the platform's own words (a student IS a
`customer`, office staff ARE `employee`s). The storefront's create door
offers all seven, but anything beyond Student is a **claim**
(`users.requested_role`), not a grant: the office decides it under ops
Team & access, approval is the promotion (it ends the person's sessions so
the new role arrives whole), and declining leaves the account a student.
Office staff may confer students, teachers and volunteers; only the admin
flag confers staff, directors, board members and donors — and a director's
approval carries the flag, because running the organisation is the admin
surface. Views follow the role: volunteers share the learner portal,
teachers land on the ops Learning tab, board members and donors get a
profile-only rail — an account to be reached at, not a console.

Every door refuses to mint. The four surfaces share one users table per
tenant, and all their sign-ins are sign-ins: an unknown name is a 404,
not a brand-new customer (that silent find-or-create is how a founder on
one tenant "became" a shopper on another). Accounts are created in
exactly two places — the storefront's create door (which files a role
claim for anything beyond student) and the ops "New team account" door,
which requires the admin key: the key IS the authority the claims queue
exists to consult, so a key-holder's create confers the role directly
(the role, not the admin flag — only owner and director carry that).
The bare API's mode-less login keeps find-or-create for scripts and dev.

The third way in is an **invitation**: the office mints a link
(`POST /api/roles/invites`, minting takes the same right as granting)
that carries a role, and whoever opens `/join/{token}` signs up straight
into it — no queue. Bound to a premade account (ops Learning → The team →
Add person), the sign-up claims that account: name fixed, password set,
role wired, single-use. The team desk on the Learning tab also edits and
deactivates teachers, tutors, office staff and volunteers, and a
**Customers** tab (Sell group, `selling` cap) finally shows the consumer
half of the CRM — orders, spend and enrolments per person. Courses
archive (active=0; every record stands) or delete only when they have no
history; library items carry a QR label (`bc:item:<uid>`, scan-at-desk
lookup), partial edits including copies (retire worn ones) and owner, and
removal that retires when loan history exists and deletes only when
nothing ever referenced them.

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
source's people-photos have no counterpart here yet. QR identity cards ARE
ported (`erp/backend/identity.py`): every person can mint an unguessable
UUID card from the /learn Me tab; a teacher scans it at the door
(`POST /api/learning/sessions/{sid}/scan` — the QR decides *who*, never
*whether*, so the ordinary check-in rules still apply and the row records
the teacher as marker), and a member scans a classmate's card as the
contact handshake — presenting your code IS the consent that shows your
full name. Reissue kills a lost card the same moment.

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
`turn_user` / `turn_pass`. The source's SFU transport (WHIP/WHEP) is
ported too (`storefront/frontend/rtc-sfu.js`, one client for both
surfaces, interface-identical to the mesh): configure any media server
speaking the standards — Cloudflare Realtime, MediaMTX, Janus, LiveKit
ingress — via `whip_url` / `whep_url` / `sfu_token` / `sfu_mode`, and
`chooseTransport` picks per call from the enrolled roster size, with
simulcast layers narrowed by the device's own core count. Unconfigured,
the config never promises a transport that is not there and the mesh
carries a class of up to 12, exactly as before.

## The rest of the source, now ported

The seven areas the first audit left open all landed:

- **Recordings** (`erp/backend/materials.py` + `rtc-compose.js`) —
  speaking/video quiz answers (raw-body uploads, magic-byte sniffing,
  token-named sharded storage; the response points at the material and
  the grader gets the tape), teacher drills on lessons, and class
  recording — the teacher's browser composites its received tiles onto a
  canvas, states its limits on the button, and uploads on stop.
- **The library** (`erp/backend/library.py`) — the lending desk on the
  ops Learning tab; availability is copies minus open loans, derived on
  read; the bookworm badge awards at checkout, ever-borrowed.
- **Lookup + speech** — shipped as the priced **Voice & translation**
  capability ($30, depends Learning): `erp/backend/lookup.py` (offline
  glossary/thesaurus first, LibreTranslate/Datamuse only by deliberate
  config, every answer says `via` where it came from) plus browser-side
  dictation and TTS in the /learn lookup panel. Revoked = the panel
  never renders and the four API doors are 404s.
- **QR identity** — see the community section above.
- **Data rights** (`erp/backend/datarights.py`) — self-service export
  from the Me tab (their record, never their keys, never a DM);
  admin-side export and erasure with the SHOWN plan — deleted /
  anonymised / retained with why — confirmed by the typed name. Erasure
  is a tombstone: files first, community rows whole, sign-ins rotated,
  the audit log keeps what happened with their name taken off it.
- **The calendar** — month grid on the learner's course page (Monday
  weeks, local day keys, the DST fix), fed by
  `GET /api/learn/courses/{cid}/sessions` where `mine` is the viewer's
  own attendance and nobody else's; recordings badge the day.
- **SFU transport** — see the live-video section above.

Still deliberately absent: the source's people-photos, and central
SFU-side recording (record where the media server is, once one exists).
