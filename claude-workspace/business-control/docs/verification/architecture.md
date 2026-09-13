# Architecture — <release or date>

*How the system is built, one section per component, with a check for every claim. Copy the component block once per process, surface, store, pipeline stage or boundary. Add sections as the system grows; delete blocks that do not apply.*

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

<!-- repeat: one block per component (a process, a surface, a data store, a pipeline stage, an external boundary) -->
### 2.n · <Component name>

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

<!-- end repeat -->

## 3. Cross-cutting

<!-- repeat: one block per concern that crosses components (tenancy, auth, audit, i18n, errors, logging, backups…) -->
### 3.n · <Concern>

| | |
|---|---|
| **Rule** | (the invariant, in one sentence) |
| **Where enforced** | |
| **Where it could be bypassed** | |

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

<!-- end repeat -->

## 4. Decisions

<!-- repeat: one row per decision the shape depends on -->
| Decision | Chosen | Instead of | Because | Revisit when |
|---|---|---|---|---|
| | | | | |

## 5. Known gaps

| Gap | Risk | Owner | Planned for |
|---|---|---|---|
| | | | |

## Sign-off

| Release | Commit | Verified by | Date | Mismatches (row → defect) |
|---|---|---|---|---|
| | | | | |
