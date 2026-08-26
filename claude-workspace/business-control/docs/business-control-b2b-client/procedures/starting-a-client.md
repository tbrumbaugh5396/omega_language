# Procedure — starting a client

**When:** the deposit clears. 
Not when the contract is signed, not when they say yes on a call.

**Takes:** about 30 minutes.

---

## 1. Make the folder

```bash
cp -R docs/business-control-b2b-client/clients/_template docs/business-control-b2b-client/clients/[client-slug]
```

Lowercase, hyphens, no spaces — it becomes a path and a URL more than once.

## 2. Fill the status board

Open `clients/[client-slug]/README.md` and fill the header: contract value, tier, dates, the **named approver**, and what they bought. Everything else fills in as you go.

## 3. Copy in what already exists

The discovery brief and the signed proposal move from wherever you drafted them into `01-consultation/` and `02-proposal/`. 
The signed contract goes into `03-agreement/`.

> Copy, don't link. In two years the folder must stand alone, and a link to a
> drafting tool you no longer pay for is not a record.

## 4. Send the kickoff pack

All five documents at once, today:

- Welcome guide
- Branding questionnaire
- Technical questionnaire
- Asset checklist
- Content planner
- **Project roadmap**, filled in with their real dates

Sending them one at a time feels considerate and adds a week.

> The roadmap is the only one of the six you'll send again. Copy it into
> `04-kickoff/to-client/`, fill every date, and put a weekly reminder in your
> calendar to update and re-send it. A client reading their own status every
> Friday does not ring you on a Tuesday.

## 5. Set the dates that matter

| Date | Put it where |
|---|---|
| Content deadline | In writing to the client, and in the status board |
| Requirements sign-off target | Status board |
| Round 1 and round 2 windows | Status board |
| Launch window — **not a Friday** | Client's calendar and yours |

## 6. Set up the build

Follow phase 0 of the [roadmap](../roadmap.md#phase-0--setup-before-the-client-sees-anything).
Back up `data/config.json` the moment it exists.

---

**Done when:** the folder exists, the pack is sent, the content deadline is in writing, and a staging URL is reachable.
