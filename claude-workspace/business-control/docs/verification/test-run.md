# Test run — [TEST TYPE] — [RELEASE OR DATE]

*Internal. Never send this to a client. One record per run of one test type — a BDD integration run, manual QA, a smoke or sanity pass, automated regression, the full manual regression, UAT. Every list grows by its count.*

| | |
|---|---|
| **Test type** (integration · system · UAT · smoke · sanity · regression · other) | [TEST TYPE] |
| **Release** | |
| **Commit** | |
| **Environment** (URL, build, data, devices) | [ENVIRONMENT] |
| **Run by** | [RUN BY] |
| **Reviewed by** (QA, for completeness) | [REVIEWED BY] |
| **Date** | |
| **Tooling** (framework, runner, Selenium suite, none) | [TOOLING] |

## 1. Scope

*Repeat from here once per area or feature in scope — how many: [HOW MANY]*

| # | Area · feature | In scope because | Out of scope (and why) |
|---|---|---|---|
| [N] | | | |

*End of the repeated block.*

## 2. Cases

*Given · when · then for BDD; steps for manual. One row per case. A case with no expected result is not a case.*

*Repeat from here once per case — how many: [HOW MANY]*

| # | Case (given · when · then, or steps) | Expected | Result | Defect |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

## 3. Defects found

*Repeat from here once per defect — how many: [HOW MANY]*

| # | Case | What happened | Severity (blocker · major · minor) | Filed as | Fixed in |
|---|---|---|---|---|---|
| [N] | | | | | |

*End of the repeated block.*

## 4. Completeness review

*QA reads the cases against the requirements and the design. A requirement with no case here is a gap, not a pass.*

*Repeat from here once per requirement checked for a case — how many: [HOW MANY]*

| # | Requirement | Cases that cover it | Gap? |
|---|---|---|---|
| [N] | | | |

*End of the repeated block.*

## 5. Verdict

| | |
|---|---|
| **Passed / total cases** | [PASSED] / [TOTAL] |
| **Open blockers** | [BLOCKERS] |
| **Verdict** (pass · pass with defects · fail) | [VERDICT] |

## Sign-off

| Release | Commit | Run by | Reviewed by | Date |
|---|---|---|---|---|
| | | | | |
