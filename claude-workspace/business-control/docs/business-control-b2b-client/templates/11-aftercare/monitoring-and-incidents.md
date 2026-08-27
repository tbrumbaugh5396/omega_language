# Monitoring & incident response — [CLIENT]

> Schedule to the [care plan](care-plan-agreement.md). Severities and response
> times live in [support & defects](support-and-defects.md).

**Studio:** [YOUR LEGAL NAME] · **Client:** [CLIENT LEGAL NAME]
**Site:** [URL] · **Plan:** ☐ Essential ☐ Standard ☐ Priority · **From:** [DATE]

"We monitor the site" means nothing until it says what is watched, what counts
as wrong, and who gets woken up. This page says all three.

---

## What is watched

| Check | How often | Alerts when | Plan |
|---|---|---|---|
| **Uptime** — homepage, from [3] locations | Every **[1] min** | Down from ≥2 locations for **[2] checks** | All |
| **Key journeys** — [contact form / checkout / login], run for real | Every **[15] min** | Two consecutive failures | Standard, Priority |
| **Errors** — server 5xx rate | Continuous | Above **[1]%** of requests over [5] min | Standard, Priority |
| **Performance** — [LCP] on [KEY PAGES] | Daily | Over **[2.5s]** for [3] days | Standard, Priority |
| **SSL certificate** expiry | Daily | **[21] days** out | All |
| **Domain** expiry | Daily | **[45] days** out | All |
| **Backups** — did last night's run and verify | Daily | Any failure, first occurrence | All |
| **Malware / defacement** — file integrity, blocklists | Daily | Any hit | All |
| **Broken links & 404s** on visited pages | [Monthly] | New 404 on a linked page | Standard, Priority |
| **Dependency vulnerabilities** | Weekly | Severity per the [security schedule](security-and-compliance.md) | All |

**Retention:** monitoring data kept **[13] months**, so this year can be
compared with last.

---

## Who hears about it

**Alerts go to the Studio first, not to you.** A pager that fires at the
client is a monitoring system that has made its problem yours.

| Severity | Studio | Client told | How |
|---|---|---|---|
| **P1** | Immediately, [24/7 on Priority] | **Within [30] min** of confirming | Phone, then email |
| **P2** | Immediately, business hours | Within **[2] hours** | Email to [CONTACT] |
| **P3 / P4** | Queued | In the monthly report | Report |

**Escalation** when the first responder can't clear a P1 inside **[60]
minutes**: [SECOND RESPONDER], then [ESCALATION CONTACT], then the host's
priority channel. Nobody sits on a dead site waiting to look competent.

**Your escalation contact** — the person we may call out of hours, and their
backup:

| | Name | Role | Phone | Email |
|---|---|---|---|---|
| Primary | | | | |
| Backup | | | | |

**Keep this current.** An incident at 21:40 is a bad moment to discover the
only number we hold belongs to someone who left in March.

---

## During an incident

1. **Confirm** it's real — not a monitoring blip — and set severity
2. **Tell you**, at the times above, with what we know and what we don't
3. **Stabilise first**: roll back, fail over, or put up a holding page
4. **Fix**, then verify from outside our own network
5. **Update you** at least every **[60] min** while a P1 is open, even when
   the update is "still working, nothing new"
6. **Write it up** within **[3] working days**: what happened, what caused it,
   what changes so it doesn't recur

A post-incident note that changes nothing is a note nobody needed. If the
answer is a monitoring gap, this schedule gets a new row.

---

## Maintenance windows

Planned work runs **[DAY, TIME, TIMEZONE]**, announced **[48] hours** ahead if
it risks visible downtime. Security patches rated critical are applied as soon
as tested, window or not — you are told after, not asked before.

---

## What you get in writing

| | Essential | Standard | Priority |
|---|---|---|---|
| Uptime figure for the month | ✓ | ✓ | ✓ |
| Incidents, with causes | ✓ | ✓ | ✓ |
| Updates applied | ✓ | ✓ | ✓ |
| Performance trend | — | ✓ | ✓ |
| Traffic & journey completion | — | Quarterly | Monthly |
| Review call | Annual | Biannual | Quarterly |

---

## What monitoring does not do

- It does not prevent outages; it shortens them
- It does not watch what it isn't pointed at — new pages, new journeys and new
  domains have to be added, and adding them is included
- It does not cover systems the Studio doesn't run: your email, your CRM, your
  payment provider's own outage
- Uptime figures are ours, measured from our checks, and will not match a
  third-party tool to the decimal

---

## Signatures

*Signing electronically? Skip the table — each party's signature, with its
timestamp and document fingerprint, is recorded in the **Signed** block that
appears at the end of this document once it's signed. The table below is for
wet-ink execution on paper.*

| | Studio | Client |
|---|---|---|
| Name | | |
| Signature | | |
| Date | | |

Agreed: [SIGN HERE]
