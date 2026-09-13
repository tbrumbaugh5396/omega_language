# Architecture — [RELEASE OR DATE]

*Internal. Never send this to a client. How the system is built, one section per component, with a check for every claim. Copy the component block once per process, surface, store, pipeline stage or boundary. Add sections as the system grows; delete blocks that do not apply.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Prepared by** | |
| **Date** | |
| **Sources read** | (files, docs, diagrams you used) |

## 1. Overview

*Three to six sentences: what runs, where, and how the pieces reach each other. A drawing may replace the prose; attach it and name it here.*

## 2. Components

*Repeat from here once per component (a process, a surface, a data store, a pipeline stage, an external boundary) — how many: [HOW MANY]*

### 2.[N] · [COMPONENT NAME]

| | |
|---|---|
| **Kind** | process · surface · store · middleware · boundary · other |
| **Lives in** | (path or service) |
| **Responsibility** | (one sentence) |
| **Talks to** | (components, in and out) |
| **Owns** | (data, files, keys, ports) |
| **Does not** | (what it deliberately leaves to another component) |

| # | Claim about this component | How to check | Result | Initials |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

*End of the repeated block.*

## 3. Cross-cutting

*Repeat from here once per concern that crosses components (tenancy, auth, audit, i18n, errors, logging, backups…) — how many: [HOW MANY]*

### 3.[N] · [CONCERN]

| | |
|---|---|
| **Rule** | (the invariant, in one sentence) |
| **Where enforced** | |
| **Where it could be bypassed** | |

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

*End of the repeated block.*

## 4. Decisions

*Repeat from here once per decision the shape depends on — how many: [HOW MANY]*

| Decision | Chosen | Instead of | Because | Revisit when |
|---|---|---|---|---|
| | | | | |

*End of the repeated block.*

## 5. Known gaps

| Gap | Risk | Owner | Planned for |
|---|---|---|---|
| | | | |

## Sign-off

| Release | Commit | Verified by | Date | Mismatches (row → defect) |
|---|---|---|---|---|
| | | | | |
