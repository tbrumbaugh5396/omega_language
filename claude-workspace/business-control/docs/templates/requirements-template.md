# Requirements — [PROJECT NAME]

**Client:** [NAME] · **Version:** [1.0] · **Date:** [DATE]
**Prepared by:** [YOU] · **Approver:** [CLIENT NAME, ROLE]

> **This document is the scope of record.** Once signed, it is what "in scope"
> means for the rest of the project. Anything not written here is a change
> order — not a refusal, just a separate quote.
>
> Read it properly. An hour now is worth a fortnight later.

---

## 1. In one paragraph

[What is being built and why, in plain language. Someone who wasn't on the
call should understand the project from this alone.]

## 2. Objectives

What this project must achieve, in priority order.

| # | Objective | How we'll know it worked |
|---|---|---|
| 1 | [e.g. Generate qualified enquiries] | [e.g. ≥15 form submissions/month by month 3] |
| 2 | | |
| 3 | | |

**Explicit non-goals** — worth stating, because they prevent drift:

- [e.g. This project is not an e-commerce build]
- [e.g. We are not redesigning the logo]

## 3. Audience

| Audience | What they need | What they do on the site |
|---|---|---|
| [Primary] | | |
| [Secondary] | | |

## 4. Sitemap

Every page. If it isn't listed, it isn't in scope.

```
Home
├── About
│   └── Team
├── Services
│   ├── [Service 1]
│   └── [Service 2]
├── Work / Case studies
├── Journal            [template + index]
└── Contact
```

**Total pages:** [N] unique templates, [N] content pages

## 5. Page-by-page

Repeat per page. Keep it brief — this is a specification, not a design.

### [PAGE NAME]

- **Purpose:** [one line]
- **Primary action:** [what we want the visitor to do]
- **Sections:** [hero, intro, three-up features, testimonial, CTA band]
- **Content owner:** [Client / Studio]
- **Notes:** [anything unusual]

## 6. Functionality

Be specific. Vagueness here becomes an argument later.

| # | Requirement | Priority | Notes |
|---|---|---|---|
| F1 | Contact form → [EMAIL], with spam protection | Must | |
| F2 | Journal with categories and pagination | Must | |
| F3 | Newsletter signup → [PLATFORM] | Should | |
| F4 | [Search] | Could | |

**Priority meanings:** *Must* = launch blocker. *Should* = included, dropped
only by agreement if the schedule slips. *Could* = only if time allows;
assume it won't.

## 7. Integrations

| System | What it does | Who provides access | Status |
|---|---|---|---|
| [CRM] | [Form submissions create a lead] | Client | |
| [Email] | [Newsletter signups] | Client | |
| [Analytics] | | Studio | |

## 8. Content

| Item | Owner | Due | Status |
|---|---|---|---|
| Homepage copy | Client | [DATE] | |
| Service page copy ×[N] | Client | [DATE] | |
| Team photos | Client | [DATE] | |
| Logo, vector | Client | [DATE] | |

See the [content planner](content-planner.md) and
[asset checklist](asset-checklist.md).

## 9. Technical

- **Platform:** [CMS / framework]
- **Hosting:** [where; who pays]
- **Domain:** [registrar; who holds it]
- **Browsers:** current and previous major Chrome, Safari, Firefox, Edge
- **Accessibility target:** WCAG 2.1 AA where content allows
- **Performance target:** [e.g. Lighthouse ≥90 mobile]
- **Redirects:** [N] URLs mapped from the old site

## 10. Design direction

- **Brand assets:** [what exists — logo, palette, type, guidelines]
- **Direction agreed:** [one or two lines from the branding questionnaire]
- **References the Client likes:** [links, with the reason for each]
- **Constraints:** [must use existing brand colours / must match print
  collateral / etc.]

## 11. Explicitly out of scope

Listed so nobody is surprised. Each is available as a change order.

- [e.g. E-commerce]
- [e.g. Multi-language]
- [e.g. Copywriting — Client is providing all text]
- [e.g. Photography]
- [e.g. Migration of the old blog archive]

## 12. Assumptions

If any of these turns out to be false, the schedule or price may change.

- Content arrives by the dates in section 8
- The Client has rights to all supplied images
- [NAMED APPROVER] is the sole approver
- Existing hosting can run [PLATFORM]
- [OTHER]

## 13. Feedback and approvals

- **[N] rounds of feedback are included**, per the signed agreement:
  - **Round 1** — [homepage / design direction]
  - **Round 2** — [full site / polish]
- One consolidated response per round, within **[5] working days**
- Approver: **[NAME]**
- Additional rounds: **$[X]** each
- Changes to anything approved in an earlier round are change orders

## 14. Schedule

| Milestone | Date |
|---|---|
| Requirements signed | [DATE] |
| Content due | [DATE] |
| Round 1 presented | [DATE] |
| Round 2 presented | [DATE] |
| Launch | [DATE] |

---

## Sign-off

By signing, the Client confirms this document accurately describes what is
being built, and understands that anything not described here is a change
order.

| | Studio | Client |
|---|---|---|
| Name | | |
| Signature | | |
| Date | | |

*Use the [requirements sign-off form](requirements-feedback-form.md) to
collect corrections before signing.*
