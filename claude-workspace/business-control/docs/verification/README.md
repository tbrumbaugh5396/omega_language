# Verification templates

*Internal. Blank masters the team fills in by hand to verify a release: what the software is, how the code is organised, what it is required to do, how it behaves, how it was tested, and how much of it the tests reached. Nothing here is generated; nothing here goes to a client.*

## How to use them

1. **Copy, never edit the master.** For a release, make
   `releases/<YYYY-MM-DD>/` and copy every template into it. The masters
   stay blank.
2. **Grow by repeating blocks.** Every template has one or more blocks
   marked *repeat*: a module, a requirement, a walkthrough, a file. Copy
   the block as many times as the release needs. A block you do not need
   is deleted, not left blank.
3. **Fill from the codebase, not from memory.** Each block says what to
   look at. Write what you found, in words a new team member could act
   on. "ok" is not a finding.
4. **Every claim gets a check.** The verification tables have a *How to
   check* column: write the command or the click path, then the result.
5. **Sign the bottom.** Release, commit, who, date, and every mismatch
   with the defect it became. An unsigned sheet was not done.

| Template | What it verifies | Fill it in when |
|---|---|---|
| [architecture.md](architecture.md) | The system's shape: processes, surfaces, storage, pipeline, boundaries | every release; any change to the shape |
| [code-organization.md](code-organization.md) | Where each module lives, what it owns, the rules it keeps | every change that adds or moves a module, table or screen |
| [requirements.md](requirements.md) | Each requirement, its implementation, its proof, and that the proof ran | every release; whenever a requirement changes |
| [behaviour.md](behaviour.md) | What a person sees at the keyboard, walked through by someone who did not build it | every release, on the built artifact |
| [testing.md](testing.md) | The suite ran on this commit, on the awkward dates, and its guards are standing | every release |
| [code-coverage.md](code-coverage.md) | Coverage per area against the floors, and a reason for every unreached sensitive line | every release |

Related: the procedures for review, coverage and the test report live in
`../business-control-b2b-client/procedures/`; the artifacts those produce
live in `../../reports/`; the client's view of all this is stage 08 of the
kit.
