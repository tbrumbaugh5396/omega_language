# The business control b2b

Everything needed to take a business project from first email to handover, and to run
it after that.

## Folder Contents

```
business-control-b2b-client/
├── README.md
├── roadmap.md      how work is delivered, deployed and set up
├── playbook.md     why the process is shaped this way
├── templates/      blank masters, one folder per stage
├── procedures/     how the studio executes — for whoever is doing the work
└── clients/        one folder per client, kept for good
```

**New here?** Read the [playbook](playbook.md) once. 
It's the whole process end
to end, with the reasons behind each step and the mistakes that cost the most.
Then work from the stage folders.

---

## Where am I, and what do I owe them?

Open the stage folder — each one's README says what gets sent, what has to come
back, and what opens the next gate.

| Stage | What's happening | Send them | Gate |
|-------|---|---|---|
| [01 · Potential customer](templates/01-potential-customer/) | An enquiry arrived | [First reply](templates/01-potential-customer/email-scripts.md) | They book a call |
| [02 · Consultation](templates/02-consultation/) | Finding out what they need | [Packages & process](templates/02-consultation/packages-and-process.md) | Discovery brief written |
| [03 · Proposal](templates/03-proposal/) | Pricing it | [Proposal](templates/03-proposal/proposal-template.md), [deck](templates/03-proposal/sales-deck.html), and  [rates](templates/03-proposal/rate-card.md) | They pick an option in writing |
| [04 · Agreement](templates/04-agreement/) | Making it real | [Contract](templates/04-agreement/contracts/) | **Signed + deposit cleared** |
| [05 · Kickoff](templates/05-kickoff/) | Gathering inputs | [Welcome guide](templates/05-kickoff/welcome-guide.md) + 4 questionnaires | Questionnaires returned, content deadline agreed |
| [06 · Requirements](templates/06-requirements/) | Agreeing what you're building | Requirements + sign-off form | **Signed requirements** |
| [07 · Brand exploration](templates/07-brand-exploration/) | *Optional* — deciding how it looks | Directions, then the [art direction](templates/07-brand-exploration/art-direction.md) | **Signed art direction** |
| [08 · Build](templates/08-build/) | Making it, showing it | Feedback forms, change orders | Round 2 signed off |
| [09 · Launch](templates/09-launch/) | Going live | Launch summary | Live, verified, **paid** |
| [10 · Handover](templates/10-handover/) | Giving them the keys | Handover pack | They can sign in without you |
| [11 · Aftercare](templates/11-aftercare/) | Keeping it | Care plan, testimonial request | Plan signed or declined |

**Stage 07 is optional.** Skip it for a week website — they have a brand and
you're applying it. Run it whenever the look is the point: a fully custom
build, or anything where "I'll know it when I see it" would otherwise get
answered inside the build stage, which is how a fortnight disappears.

**How the work is actually delivered** — what they physically receive, in what
format, and how it gets deployed into their own accounts — is the
[roadmap](roadmap.md).

---

## The three folders, and why they're separate

**[`templates/`](templates/)** — blank masters. Never fill one in place; copy
it into the client's folder first. A master with someone's name in it is how
the next client gets a proposal addressed to the last one.

**[`procedures/`](procedures/)** — how the studio executes. The templates are
the paperwork; these are the instructions for the person doing the work, written
so a competent someone in their first week can follow them today.

**[`clients/`](clients/)** — one folder per client, and every stage inside it
splits `to-client/` from `internal/`. Copy [`_template`](clients/_template/) to
start one.

> Keep the internal wall. The one-folder version fails in a specific and
> expensive way: someone zips the project to "send everything over", and the
> client reads your hourly estimate, your gut call about their decision-making,
> and the line where you wrote down what would make you regret taking the job.

---

## Two doors into a project

Not every enquiry is a website. Stage 02 has a door for each.

**"We need a new site."** [Sales call
questionnaire](templates/02-consultation/sales-call-questionnaire.md).
Forty-five minutes on the business, priced against the four website tiers.

**"Everything behind the shop is spreadsheets."** [Free
consultation](templates/02-consultation/free-consultation.md) instead. Ninety
minutes on the machinery: what they run today, what it costs in subscriptions
*and* in re-typing, which modules and roles they need, what has to migrate. It
ends in a sizing score that lands on a package.

The free consultation is free on purpose — they leave with a written map of
their own stack whether or not they hire you, and that map is why the proposal
reads as an obvious next step rather than a cold number. Both doors converge on
the same [discovery brief](templates/02-consultation/discovery-brief.md) →
[proposal](templates/03-proposal/proposal-template.md) → contract.

---

## Five rules that make the paperwork pay for itself

**Nothing starts without a deposit and a signature.** Not "we'll sort the
paperwork as we go". The deposit is the client deciding they're serious.

**Requirements get signed before design starts.** The [requirements
doc](templates/06-requirements/requirements-template.md) is the thing you point
at for the rest of the project. Without it, "that's not what I asked for" has no
answer.

**Two feedback rounds. Written into the price, written into the contract.**
Round 1 on the homepage direction, round 2 on the full site. Each is one
consolidated response within five working days. A third is a paid add-on. This
single clause is the difference between a profitable studio and free work
forever — see [why](playbook.md#the-revision-trap).

**Anything not in the requirements is a change order.** Say it warmly, say it
every time. The [change order](templates/08-build/change-order.md) takes two
minutes; the cost of *not* using it is the whole margin.

**Content is the critical path, always.** Every late project was late because
copy and photos didn't arrive. Ask on day one, chase weekly, and put the stall
in writing when it happens.

---

## On the contracts

The four contracts are drafted from ordinary commercial practice and are a
**sound starting point, not legal advice.** Before sending one to a real client,
have a lawyer in your jurisdiction read it once — the payment terms, the IP
transfer, the revision limit and the liability cap especially. It's a one-off
cost that protects every project afterwards.

| Tier | What it is | Typical range | Revisions |
|------|-----------|---------------|-----------|
| [Week website](templates/04-agreement/contracts/week-website.md) | Existing template, client's content, fixed scope, one week | $1,500 – $4,000 | 1 round |
| [Partially custom](templates/04-agreement/contracts/partially-custom.md) | Template foundation, custom sections and design | $5,000 – $15,000 | 2 rounds |
| [Fully custom](templates/04-agreement/contracts/fully-custom.md) | Designed and built from scratch, bespoke functionality | $18,000 – $60,000+ | 2 rounds per phase |
| [Branding & creative](templates/04-agreement/contracts/branding-creative.md) | Identity, art direction, motion, campaign assets | $6,000 – $40,000 | 2 rounds per deliverable |

All four share the same spine — see [common
clauses](templates/04-agreement/contracts/common-clauses.md).
