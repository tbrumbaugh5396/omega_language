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

## Still waiting from the source

- Student-to-student **social** (contacts, DMs, blocks, ghosts, reports)
  and the **video tutoring** WebRTC rooms — the platform has staff chat and
  calls, but the learner-facing versions are unported.
- **Library loans** (and the bookworm badge), speaking/video quiz answers
  (the grading engine already understands them; recording UI is what's
  missing — they refuse at authoring rather than sit unmarkable).
