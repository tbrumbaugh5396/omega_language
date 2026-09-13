# Code organisation — [RELEASE OR DATE]

*Internal. Never send this to a client. Where things go, what each part owns, and the rules the tree keeps. Every list below grows by its count: answer how many and that many blocks or rows are laid out.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Prepared by** | |
| **Date** | |

## 1. Layout

*Paste the top-level tree (two levels is usually enough), then one row per directory.*

```
[TREE]
```

*Repeat from here once per directory — how many: [HOW MANY]*

| # | Directory | Belongs here | Does not belong here |
|---|---|---|---|
| [N] | | | |

*End of the repeated block.*

## 2. Areas and modules

*Repeat from here once per area (a directory of modules) — how many: [HOW MANY]*

### 2.[N] · [AREA] — `[PATH]`

*What this area is for:* [PURPOSE]

*Repeat from here once per module in the area — how many: [HOW MANY]*

| # | Module | Purpose (one line) | Owns (tables, files, state) | Exposes (routes, functions, screens) | Depends on | Sensitive? |
|---|---|---|---|---|---|---|
| [N] | | | | | | |

*End of the repeated block.*

*End of the repeated block.*

## 3. The rules

*Repeat from here once per rule — how many: [HOW MANY]*

| # | Rule | Enforced by (test guard · review · tooling) | Where |
|---|---|---|---|
| R[N] | | | |

*End of the repeated block.*

## 4. Verification

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| O1 | Every module in section 2 exists at the path given | | | |
| O2 | Every module has a stated purpose | | | |
| O3 | No two modules own the same table or file | | | |
| O4 | Every rule in section 3 is enforced where it says | | | |
| O5 | Nothing runtime-generated or secret is tracked | | | |

*Repeat from here once per further claim — how many: [HOW MANY]*

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| O5+[N] | | | | |

*End of the repeated block.*

## 5. Changes since the last sheet

*Repeat from here once per module added, moved, removed or grown — how many: [HOW MANY]*

| # | Module | Added · moved · removed · grew | Why | Review record |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

## Sign-off

| Release | Commit | Verified by | Date | Mismatches (row → defect) |
|---|---|---|---|---|
| | | | | |
