# Clients

One folder per client. Copy `_template/` and name it after them — lowercase,
hyphens, no spaces, because it becomes a path more than once.

```bash
cp -R docs/business-control-b2b-client/clients/_template docs/business-control-b2b-client/clients/[client-slug]
```

Then follow [starting a client](../procedures/starting-a-client.md).

## What goes where

Every stage folder has the same two sides, and the split is the point:

| | Holds | Rule |
|---|---|---|
| `to-client/` | Anything they have received or will receive | Assume they will read it. Nothing in here should surprise them |
| `internal/` | Briefs, estimates, notes, risk calls | **Never send.** If it would be awkward to forward, it belongs here |

> The split exists because the one-folder version fails in a specific and
> expensive way: someone zips the project folder to "send everything over" and
> the client reads your hourly estimate, your gut call about their
> decision-making, and the line where you wrote down what would make you regret
> taking the job. Keep the wall.

Each client's `README.md` is the status board — stage, dates, money, content
percentage, current risk. It gets updated in the [weekly
rhythm](../procedures/weekly-rhythm.md), not when someone remembers.

## Keep the folder for good

Copy documents in rather than linking out. In two years this folder must stand
alone: a link to a drafting tool you stopped paying for is not a record, and
the handover document is the thing you will both want when something needs
changing and nobody remembers how it works.
