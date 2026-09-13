# Code organisation — [RELEASE OR DATE]

*Internal. Never send this to a client. Where things go, what each part owns, and the rules the tree keeps. Copy the area block once per top-level area, and the module block once per module inside it. Add areas as the tree grows.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Prepared by** | |
| **Date** | |

## 1. Layout

*Paste the top-level tree (two levels is usually enough) and write one line per directory saying what belongs there and what does not.*

```
[PASTE TREE]
```

| Directory | Belongs here | Does not belong here |
|---|---|---|
| | | |

## 2. Areas and modules

*Repeat from here once per area (a directory of modules) — how many: [HOW MANY]*

### 2.[N] · [AREA] — `[PATH]`

*What this area is for, in a sentence.*

*Repeat from here once per module in the area — how many: [HOW MANY]*

| Module | Purpose (one line) | Owns (tables, files, state) | Exposes (routes, functions, screens) | Depends on | Sensitive? |
|---|---|---|---|---|---|
| | | | | | |

*End of the repeated block.*

*End of the repeated block.*

## 3. The rules

*Repeat from here once per rule — how many: [HOW MANY]*

| # | Rule | Enforced by (test guard · review · tooling) | Where |
|---|---|---|---|
| R1 | | | |
| R2 | | | |

*End of the repeated block.*

## 4. Verification

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| O1 | Every module in section 2 exists at the path given | | | |
| O2 | Every module has a stated purpose | | | |
| O3 | No two modules own the same table or file | | | |
| O4 | Every rule in section 3 is enforced where it says | | | |
| O5 | Nothing runtime-generated or secret is tracked | | | |
| | (add rows) | | | |

## 5. Changes since the last sheet

| Module | Added · moved · removed · grew | Why | Review record |
|---|---|---|---|
| | | | |

## Sign-off

| Release | Commit | Verified by | Date | Mismatches (row → defect) |
|---|---|---|---|---|
| | | | | |
