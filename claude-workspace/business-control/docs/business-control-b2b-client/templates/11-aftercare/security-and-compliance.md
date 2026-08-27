# Security & compliance schedule — [CLIENT]

> Schedule to the [care plan](care-plan-agreement.md), and the named list
> clause 15 of the [agreement](../04-agreement/contracts/common-clauses.md)
> refers to. Starting point, not legal advice — where a law applies to your
> business, take your own.

**Studio:** [YOUR LEGAL NAME] · **Client:** [CLIENT LEGAL NAME]
**Site:** [URL] · **Plan:** ☐ Essential ☐ Standard ☐ Priority · **From:** [DATE]

Security is not a feature that ships once. It is a cadence, a list of who
holds which key, and an agreement about what happens on the bad day.

---

## Patching

| Rated | Applied within | Window |
|---|---|---|
| **Critical** — actively exploited, or remote code execution | **[24] hours** of a fix existing | Immediately, no window |
| **High** | **[7] days** | Next maintenance window |
| **Medium** | Next scheduled run | Monthly / fortnightly / weekly by plan |
| **Low** | Batched | Quarterly |

Every update is applied **after a backup**, checked against the key journeys
in the [monitoring schedule](monitoring-and-incidents.md), and rolled back if
it breaks something. Where a component is abandoned upstream and can't be
patched, the Studio says so in writing and quotes the replacement.

**Dependency scanning** runs **weekly** across [PLATFORM, PLUGINS, LIBRARIES],
against [SOURCE — e.g. the platform advisory feed and the CVE database].

---

## The baseline we keep

- **TLS** current, [1.2]+ only, certificate auto-renewed and monitored
- **Security headers**: HSTS, CSP, X-Content-Type-Options, Referrer-Policy —
  reviewed [quarterly]
- **Admin access** over MFA, no shared logins, named accounts only
- **Least privilege**: editors edit, admins administer, and nobody is an admin
  because it was quicker that day
- **Backups** [daily], held [30] days, stored [OFF-SITE LOCATION], encrypted
- **Restore tested [quarterly]** against a scratch environment, and the test
  is dated and filed — an untested backup is a belief, not a backup
- **Logs** kept [90] days: admin sign-ins, permission changes, deployments
- **Off-boarding**: any account we hold for a leaver is removed within
  **[1] working day** of you telling us

---

## Who holds what

| Credential | Held by | MFA | Reviewed |
|---|---|---|---|
| Hosting / server | | | [Quarterly] |
| Domain registrar | | | [Quarterly] |
| CMS admin | | | [Quarterly] |
| Payment provider | | | [Quarterly] |
| Analytics & ads | | | [Quarterly] |
| Email / DNS | | | [Quarterly] |

**You own every account.** The Studio holds access to work, not to hold you.
On request, or on the day the plan ends, access is transferred and ours
removed — see clause 15.

**Credentials are never sent by email or chat.** [PASSWORD MANAGER / VAULT],
or they don't move.

---

## Compliance in scope

Tick what this plan covers. What isn't ticked isn't covered, and saying so
here is cheaper than assuming it later.

| | In scope | Standard | Who is responsible |
|---|---|---|---|
| **Accessibility** | ☐ | [WCAG 2.2 AA] | Studio for delivered templates; Client for content added after |
| **Privacy / data protection** | ☐ | [GDPR / UK GDPR / CCPA / LIST] | Client is the controller; Studio is a processor under [DPA] |
| **Cookie consent** | ☐ | [BANNER + CATEGORIES] | Studio implements; Client approves the categories |
| **Payment card** | ☐ | [PCI DSS SAQ-A] — hosted fields, card data never touches the site | Studio keeps the integration; Client completes the SAQ |
| **Sector rules** | ☐ | [HIPAA / FCA / AGE-RESTRICTED / NONE] | [WHO] |
| **Records** — the register, the DPA, the sub-processor list | ☐ | | Studio maintains for what it runs |

**Annual compliance review** each [MONTH]: accessibility spot-check of the
[10] most-visited pages, cookie and consent check, sub-processor list
refreshed, this table re-agreed. Findings that are ours to fix are fixed under
the plan; findings that are yours arrive as a written list, not a lecture.

**Accessibility is only kept if content keeps it.** Templates ship compliant;
an image posted without alt text or a PDF dropped in un-tagged breaks it. The
review tells you where that has happened.

---

## The bad day

**If the site is compromised**, the Studio will:

1. Take it off the internet or into holding, if that limits harm
2. Tell you within **[4] hours** of confirming — no "let's see if we can fix
   it quietly first"
3. Preserve logs before cleaning, so what happened stays knowable
4. Restore from a clean backup, close the way in, rotate every credential
5. Give you a written account within **[5] working days**: what was reached,
   what was taken, what changed

**If personal data may have been reached**, you are the controller and the
notification clock is yours — under [GDPR] that is **72 hours** to the
supervisory authority from becoming aware. The Studio gets you what you need
to make that call inside **[24] hours**, and will not sit on a maybe.

**Cost.** Cleanup of a compromise caused by software the Studio maintains is
included. Cleanup of one caused by credentials shared outside the plan, a
Client-installed component, or another contractor is quoted first, then billed.

---

## Not in scope

- Penetration testing, red-teaming, formal audit — quoted separately
- Certifications ([ISO 27001 / SOC 2 / Cyber Essentials]) — supported with
  evidence, not obtained on your behalf
- Your internal devices, laptops, mail and network
- Systems the Studio doesn't run
- Legal opinion on whether a law applies to you

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
