# Verification templates

*Internal. Blank masters the team fills in by hand to verify a release: what the software is, how the code is organised, what it is required to do, how it behaves, how it was tested at every level from unit to demo, and how much of it the tests reached. Nothing here is generated; nothing here goes to a client.*

## How to use them

1. **Copy, never edit the master.** For a release, make
   `releases/<YYYY-MM-DD>/` and copy every template into it. The masters
   stay blank.
2. **Grow by repeating blocks.** Every template has one or more blocks
   marked *Repeat from here … how many: [HOW MANY]*. Filed from the clients
   screen, answer the count and the block is laid out that many times:
   sections numbered 1, 2, 3; table rows added under the one header. Change
   the count later and copies are added or trimmed, the ones written kept.
   On paper, copy the block by hand. A block you do not need is deleted,
   not left blank.
3. **Fill from the codebase, not from memory.** Each block says what to
   look at. Write what you found, in words a new team member could act
   on. "ok" is not a finding.
4. **Blanks are `[TOKENS]`.** Filed from the clients screen, every `[TOKEN]` is a field the vault fills by name; on paper, write over it.
5. **Every claim gets a check.** The verification tables have a *How to
   check* column: write the command or the click path, then the result.
6. **Sign the bottom.** Release, commit, who, date, and every mismatch
   with the defect it became. An unsigned sheet was not done.

| Template | What it verifies | Fill it in when |
|---|---|---|
| [architecture.md](architecture.md) | The system's shape: processes, surfaces, storage, pipeline, boundaries | every release; any change to the shape |
| [code-organization.md](code-organization.md) | Where each module lives, what it owns, the rules it keeps | every change that adds or moves a module, table or screen |
| [requirements.md](requirements.md) | Each requirement, its implementation, its proof, and that the proof ran | every release; whenever a requirement changes |
| [behaviour.md](behaviour.md) | What a person sees at the keyboard, walked through by someone who did not build it | every release, on the built artifact |
| [testing.md](testing.md) | The suite ran on this commit, on the awkward dates, and its guards are standing | every release |
| [code-coverage.md](code-coverage.md) | Coverage per area against the floors, and a reason for every unreached sensitive line | every release |
| [code-review.md](code-review.md) | One change, read by a second person: what was read, the checklist, the findings, the outcome | every change, before it merges |
| [test-strategy.md](test-strategy.md) | Every kind of test the product gets — functional, non-functional, cross-cutting, the process gates, coverage rules, static analysis rules — who does it, what breaks the build, where the evidence lives | every release; when the strategy changes |
| [test-run.md](test-run.md) | One run of one test type: BDD integration, manual QA, smoke, sanity, automated or full manual regression, UAT — scope, cases, defects, QA's completeness review, verdict | every run |
| [non-functional-run.md](non-functional-run.md) | Performance, security, usability and compatibility for a release — scenarios, thresholds, findings, platforms | every release |
| [design-review.md](design-review.md) | The design team's review of a feature before QA — what was reviewed, checklist, findings, ready-for-QA | every new feature |
| [demo-record.md](demo-record.md) | A demo to the internal group or to customers — who saw what, what they said, what changed | every demo |

Related: the procedures for review, coverage and the test report live in
`../business-control-b2b-client/procedures/`; the artifacts those produce
live in `../../reports/`; the client's view of all this is stage 08 of the
kit.
