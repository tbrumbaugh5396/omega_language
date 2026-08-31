# Hosting & infrastructure schedule

> **Not legal advice.** Drafted from ordinary commercial practice; have a
> lawyer in your jurisdiction read it once before it carries real clients —
> particularly the data-ownership, suspension and exit sections.

This schedule attaches to the Agreement between **[YOUR LEGAL NAME /
COMPANY]** ("the Studio") and **[CLIENT LEGAL NAME]** ("the Client"). It
governs the Client's install on the Studio's platform. The other contracts
in this kit assume the Client owns their hosting; **this schedule is for
the opposite arrangement**, and where the two conflict about hosting, this
schedule governs.

## 1. The grant

The Client authorises the Studio to provision, operate, move and retire the
infrastructure their install runs on. Concretely, the Studio may:

- stand the install up on a shared machine, or one dedicated to the Client;
- move it between machines for capacity, cost or maintenance reasons,
  with no visible change beyond a brief maintenance window;
- issue and renew TLS certificates for the hostnames below;
- take and store the backups described in the care-plan schedules.

The Studio decides *where* the install runs. The Client decides
*whether* it runs — see Suspension and Exit.

## 2. What is stood up

| | |
|---|---|
| Install (tenant) | **[TENANT ID]** |
| Answers at | **[HOSTNAMES]** |
| Size class | **[NODE CLASS]** — per the published price book |
| Stood up on | [DATE] |

Each install has its own database, its own configuration and secrets, its
own uploads and its own push keys. Nothing is shared with any other
business on the platform: another tenant's data is not withheld from the
Client — it is unreachable, and the same is true in reverse.

## 3. The Client's data

**The Client owns their data — all of it, at all times.** The Studio's
rights over it extend to operating, backing up and restoring the install,
and nothing further. On request the Studio provides a full export in
ordinary formats within **[5] working days**, at no charge beyond the
[second] such request in a calendar year.

## 4. Fees

Hosting is not billed separately: it is inside **Part 1 (platform)** of the
monthly bill, as set out in the price book and the Agreement. Support and
maintenance of the infrastructure — patching, monitoring, backups, restore
tests — is **Part 2 (care plan)** and is governed by its own schedules.
Third-party costs that belong to the Client (their domain name, their own
external services) remain the Client's.

## 5. Suspension

The Studio may suspend the install — for non-payment after the notice
periods in the Agreement, or at the Client's own request. Suspension is
reversible and touches no data: the hostname answers "temporarily
unavailable" (HTTP 503), not "no such site", and resuming restores service
as it was. Suspension does not stop the clock on fees unless the Agreement
says otherwise.

## 6. Exit

When the engagement ends, whoever ends it:

- The install is removed from the platform and its hostnames stop
  answering.
- **The Client's data is retained** in an offline archive for **[90]
  days**, during which the export in clause 3 remains available. It is the
  week after a cancellation that someone asks for a copy; this clause is
  why that request has a good answer.
- After the retention period — or earlier, at the Client's written request
  — the archive is permanently deleted and the Studio confirms so in
  writing.

## 7. Subprocessors

The Studio runs its machines on **[VPS PROVIDER, e.g. Hetzner / DigitalOcean]**
in **[REGION]**. The Studio may change provider or region with **[30]
days'** notice; a move never changes clauses 3, 5 or 6.

## 8. Service levels

Availability targets, response times, monitoring and incident handling are
**not** in this schedule — they are in the care-plan agreement and its
three schedules (support & defects, monitoring & incidents, security &
compliance), which travel with the plan the Client selected. This schedule
says who may build and remove things; those say how well they are run.

---

Signed for the Studio: ______________________ Date: __________

Signed for the Client: ______________________ Date: __________
