# Documentation

Two halves, and the split is deliberate.

| | |
|---|---|
| [**`product/`**](product/README.md) | How Business Control works, what it costs to run, and the architecture decisions behind it |
| [**`business-control-b2b-client/`**](business-control-b2b-client/README.md) | How to sell busines control as a b2b to clients, what the scope of work is, how to build, how to deliver and maintain it for a client |

One describes the thing. 
The other describes the business of putting it in someone else's hands. 
A document that fits both usually belongs in `product/` with a pointer from the kit — `DEPLOY.md` is the worked example: the client kit's delivery roadmap points at it rather than copying the steps, so there is one place deployment is true.

---

## Where things are

### `product/` — the software

| Document | What it answers |
|---|---|
| [DEPLOY.md](product/DEPLOY.md) | Getting an install onto the internet — VPS, TLS, systemd, hardening, backups |
| [USERS.md](product/USERS.md) | Roles, sign-in, the tab access matrix, the security model |
| [ecommerce-architecture-decision.md](product/ecommerce-architecture-decision.md) | Shopify vs. custom — own the back office, rent the money edge |
| [private-subscription-app.md](product/private-subscription-app.md) | Build subscription billing or rent it |
| [saas-scaling.md](product/saas-scaling.md) | Multi-tenancy and what hosting does to margins |
| [ecommerce-stack-deck.html](product/ecommerce-stack-deck.html) | The 39-slide walkthrough of the stack decision |

### `business-control-b2b-client/` — the engagement

| | |
|---|---|
| [`templates/`](business-control-b2b-client/templates/) | Blank masters, one folder per stage, 01 → 11 |
| [`procedures/`](business-control-b2b-client/procedures/) | How the studio executes — written for whoever is doing the work |
| [`clients/`](business-control-b2b-client/clients/README.md) | One folder per client, kept for good |
| [`roadmap.md`](business-control-b2b-client/roadmap.md) | How work is delivered, deployed and set up |
| [`playbook.md`](business-control-b2b-client/playbook.md) | Why the process is shaped the way it is |

**Where am I in a project?** Open the numbered stage folder — each one's README says what gets sent, what has to come back, and what opens the next gate. Start at the [kit's index](business-control-b2b-client/README.md).

---

## Two rules for this folder

**Runbooks are kept current; decision records are superseded, not edited.**
`DEPLOY.md` and `USERS.md` track the code — if one is wrong, it's a bug. 
The architecture documents record what was decided and on what evidence, which is
the whole reason to keep one. 
When a decision changes, write the new one and
mark the old superseded; a decision doc quietly edited to match today's plan can no longer tell you why you're where you are.

**Nothing in `clients/*/internal/` is ever sent.** Estimates, gut calls, the line where someone wrote down what would make them regret taking the job. 
The per-client folders separate `to-client/` from `internal/` for exactly one failure: somebody zips the folder to "send everything over".

---

## Running it, and the code itself

The [top-level README](../README.md) covers running Business Control locally, the module inventory, and the API. 

The three surfaces:

- storefront
- ERP/CRM and
- store admin 

are one process on one port; there is only ever one thing to
start.
