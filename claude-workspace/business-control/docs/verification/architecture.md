# Architecture — [RELEASE OR DATE]

*Internal. Never send this to a client. How the system is built, one section per component, with a check for every claim. Every list below grows by its count: answer how many and that many blocks or rows are laid out.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Prepared by** | |
| **Date** | |
| **Sources read** | (files, docs, diagrams you used) |

## 1. Overview

*Three to six sentences: what runs, where, and how the pieces reach each other. A drawing may replace the prose; attach it and name it here.*

______

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

*Repeat from here once per claim about this component — how many: [HOW MANY]*

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

*End of the repeated block.*

## 3. Cross-cutting

*Repeat from here once per concern that crosses components (tenancy, auth, audit, i18n, errors, logging, backups) — how many: [HOW MANY]*

### 3.[N] · [CONCERN]

| | |
|---|---|
| **Rule** | (the invariant, in one sentence) |
| **Where enforced** | |
| **Where it could be bypassed** | |

*Repeat from here once per claim about this concern — how many: [HOW MANY]*

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

*End of the repeated block.*

## 4. Decisions

*Repeat from here once per decision the shape depends on — how many: [HOW MANY]*

| # | Decision | Chosen | Instead of | Because | Revisit when |
|---|---|---|---|---|---|
| [N] | | | | | |

*End of the repeated block.*

## 5. Known gaps

*Repeat from here once per known gap — how many: [HOW MANY]*

| # | Gap | Risk | Owner | Planned for |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

## Sign-off

| Release | Commit | Verified by | Date | Mismatches (row → defect) |
|---|---|---|---|---|
| | | | | |
