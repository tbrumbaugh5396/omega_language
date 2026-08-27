# Running a care plan

**Internal. Never send this to a client.**

For whoever holds maintenance this month. The client bought a cadence; this is
the cadence. A plan that is billed monthly and touched when something breaks
is a plan you will lose at renewal, deservedly.

Read alongside the schedules the client signed:
[care plan](../templates/11-aftercare/care-plan-agreement.md),
[support & defects](../templates/11-aftercare/support-and-defects.md),
[monitoring & incidents](../templates/11-aftercare/monitoring-and-incidents.md),
[security & compliance](../templates/11-aftercare/security-and-compliance.md).

---

## Every month, in this order

Order matters. Backup before updates, verify after, and never patch on a
Friday afternoon unless it's critical.

1. **Backup, and confirm it landed.** Not "the job ran green" — the file
   exists and is the size it should be.
2. **Apply updates** at the plan's cadence. Platform, then plugins, then
   theme. One at a time on anything that has broken before.
3. **Walk the key journeys** listed in the monitoring schedule. By hand. The
   synthetic check knows the form submits; it doesn't know the email arrived.
4. **Read the week's alerts** — including the ones that resolved themselves.
   A flap that fixes itself three times is an outage forming.
5. **Check the vulnerability scan** and clear anything rated per the security
   schedule.
6. **Spend the included hours** — see below.
7. **Write the report** and send it, on the same date each month.

**File the evidence** in the client's `10-aftercare/internal/`: update log,
restore-test date, scan results, the report you sent. Two years from now,
"did we patch that?" needs an answer, not a memory.

**Log it in the ERP** against the client. The activity log is what a renewal
conversation is built from.

---

## Quarterly, on top

- **Restore test.** Restore to a scratch environment and open it. Date it and
  file it. An untested backup is a belief.
- **Security header and access review** — who still has admin, and should they?
- **Performance check** against the plan's budget.
- **Accessibility spot-check** of the [10] most-visited pages if accessibility
  is in scope.

**Annually:** the compliance review in the security schedule, and the
sub-processor list.

---

## The included hours

They are reserved capacity, and they don't roll over. Two failure modes,
both avoidable:

**Nobody asks.** Then you've billed for nothing visible, and at renewal they
feel it. Around day [20], if the hours are untouched, send one line: *"You've
got [N] hours left this month — anything you want changed?"* They almost
always find something, and the plan starts feeling like a service instead of
a subscription.

**They ask for a change and call it a bug.** Use the defect/change table in
the support schedule, quote it, and do it anyway if it's small — once. Twice
is a conversation about the right plan.

---

## When something breaks

Follow the incident steps in the monitoring schedule, not your instincts. The
two people usually get wrong:

- **Tell the client before you have the answer.** "The site is down, we're on
  it, next update in an hour" beats silence that they break first.
- **Preserve before you clean** on anything that looks like a compromise. A
  cleaned server has no evidence, and you will need to know what was reached.

Write the post-incident note within [3] working days. If the cause was
something monitoring should have caught, add the row to the schedule — for
this client and for the master in the kit.

---

## Renewal, and raising the price

Raise renewal in **month ten**, not month twelve, and lead with the year's
evidence: uptime, incidents caught, updates applied, hours used. It is the one
conversation where the boring log is the sales material.

**An increase is normal** — [3–5]% or the first plan that no longer fits.
Give [60] days' notice in writing and say what changed. A client who has
watched you catch things all year does not blink at [5]%.

**When to move them up a tier:** the hours run out most months, response time
keeps mattering, or the site has grown past what the plan assumed.

**When to let them go:** they treat every change as a bug, they edit the site
and expect free repairs, or they will not fix what the compliance review keeps
flagging. Give notice, hand over cleanly per clause 15, and take the weekend
back.

---

## Growth retainers are separate

If the client is also on a [growth
retainer](../templates/11-aftercare/growth-retainer.md), keep the billing,
the reporting and the cancellation separate. Bundling them means a bad ad
month puts the maintenance at risk — and the maintenance is the part that
keeps their site alive.
