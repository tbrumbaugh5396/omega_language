"""What an agent is allowed to ask for, and what it costs to be wrong.

The app answers 729 paths. Handing all of them to a language model is not
an integration, it is an accident waiting for a plausible-sounding reason:
somewhere in that list are routes that refund money, delete a tenant,
publish to a shop front and mail a customer. So this file is a short list,
chosen by hand, and the server can offer nothing that is not on it.

The list is shaped by one question asked of every route — **what happens
if the model is confidently wrong?**

  * Reading is free. A wrong read wastes a turn. Everything worth knowing
    about the business is here, because an agent that cannot see the
    business is a chat window with extra steps.

  * Writing is off unless the operator turns it on, and then only for
    things that are ADDITIVE and REVERSIBLE by a person who did not
    expect them: a note, a log line, a ticket, a draft. Somebody reading
    a note they disagree with deletes it. Somebody reading a refund they
    disagree with phones their bank.

  * Some routes are deliberately absent even with writes on, and the
    reason is not that they are dangerous in general — the operator does
    them daily. It is that they are irreversible, public, or spend money,
    which are the three things a person should still be the one to do.
    They are named in EXCLUDED below rather than left out silently, so
    the omission reads as a decision rather than an oversight.

Authorisation is NOT enforced here and must not be. The key the server
carries is bound to an account, so every call lands in the same permission
check the screens use. This list narrows what can be *attempted*; the app
decides what is *allowed*. A tool on this list called with a key bound to
a shop assistant gets the shop assistant's 403, which is the correct
answer and not a bug in the list.
"""

# Every entry: what it is called, what it does, and the request it makes.
# `query` / `path_params` / `body` are JSON-Schema property maps; anything
# in `required` must be supplied by the caller.
TOOLS = [
    # ---------- what am I, and what is this business ----------
    {
        "name": "bc_whoami",
        "summary": "Who this key acts as, and what that account may do. "
                   "Worth calling first: every other answer here is "
                   "shaped by it, and a permission refusal downstream "
                   "reads as a missing feature if you don't know.",
        "method": "GET", "path": "/api/whoami",
    },
    {
        "name": "bc_plan",
        "summary": "The business's name and the capabilities on its plan. "
                   "A screen the plan doesn't include is not missing, it "
                   "is unsold — say so rather than reporting a fault.",
        "method": "GET", "path": "/api/meta",
    },

    # ---------- selling ----------
    {
        "name": "bc_products",
        "summary": "The catalogue: every active product with SKU, price "
                   "and category.",
        "method": "GET", "path": "/api/products",
    },
    {
        "name": "bc_orders",
        "summary": "Recent orders with their status, totals and lines.",
        "method": "GET", "path": "/api/orders",
    },
    {
        "name": "bc_customers",
        "summary": "Customers, filtered by a search term over name and "
                   "email.",
        "method": "GET", "path": "/api/customers",
        "query": {"q": {"type": "string",
                        "description": "name or email fragment"}},
    },
    {
        "name": "bc_customer",
        "summary": "One customer in full: their orders, subscriptions and "
                   "contact details.",
        "method": "GET", "path": "/api/customers/{uid}",
        "path_params": {"uid": {"type": "integer",
                                "description": "customer account id"}},
        "required": ["uid"],
    },
    {
        "name": "bc_inventory",
        "summary": "Stock on hand per product per store, with the restock "
                   "level each is measured against.",
        "method": "GET", "path": "/api/inventory",
    },
    {
        "name": "bc_stores",
        "summary": "The shops and depots this business runs.",
        "method": "GET", "path": "/api/stores",
    },

    # ---------- the numbers ----------
    {
        "name": "bc_sales_summary",
        "summary": "Commerce analytics: revenue, orders, average basket "
                   "and what is selling.",
        "method": "GET", "path": "/api/analytics/commerce",
    },
    {
        "name": "bc_profit_and_loss",
        "summary": "Revenue, cost of goods, expenses and what is left. "
                   "Derived from the operational tables, so it answers "
                   "'how are we doing', not 'what do we file' — it is not "
                   "a set of books and must not be quoted as one.",
        "method": "GET", "path": "/api/analytics/pnl",
    },
    {
        "name": "bc_daily_series",
        "summary": "One row per day per region: money, orders, people, "
                   "hours, and what kind of day it was. The table to join "
                   "against when comparing any period with another.",
        "method": "GET", "path": "/api/analytics/days",
    },

    # ---------- teaching ----------
    {
        "name": "bc_classes",
        "summary": "Courses and their sessions, including which are "
                   "running now.",
        "method": "GET", "path": "/api/learning/classes",
    },
    {
        "name": "bc_student",
        "summary": "One student's whole standing: profile, attendance, "
                   "scores, progress, achievements and a dated timeline.",
        "method": "GET", "path": "/api/students/{uid}",
        "path_params": {"uid": {"type": "integer",
                                "description": "the student's account id"}},
        "required": ["uid"],
    },
    {
        "name": "bc_test_results",
        "summary": "Scores imported from GED Manager and NorthStar, and "
                   "which are still waiting to be matched to a student.",
        "method": "GET", "path": "/api/results",
    },

    # ---------- the people who work here ----------
    {
        "name": "bc_hours",
        "summary": "Everybody's worked and paid hours for the period, "
                   "with what is still unapproved.",
        "method": "GET", "path": "/api/hours/everyone",
    },
    {
        "name": "bc_shifts",
        "summary": "The published rota: who is on, when.",
        "method": "GET", "path": "/api/shifts",
    },
    {
        "name": "bc_calendar",
        "summary": "Everything this business has a date for, in one list.",
        "method": "GET", "path": "/api/calendar",
    },
    {
        "name": "bc_hiring",
        "summary": "Open postings, every applicant with their stage, and "
                   "the onboarding lists in progress.",
        "method": "GET", "path": "/api/hiring",
    },

    # ---------- money out ----------
    {
        "name": "bc_expenses",
        "summary": "Filed expenses with their category, state and the "
                   "business share of each.",
        "method": "GET", "path": "/api/expenses",
        "query": {"state": {"type": "string",
                            "description": "pending, approved, declined, "
                                           "paid or withdrawn"},
                  "year": {"type": "integer",
                           "description": "tax year, omit for the current one"}},
    },
    {
        "name": "bc_expense_summary",
        "summary": "The tax-year picture: deductible totals by category, "
                   "mileage, depreciation and the estimate that falls out "
                   "of them. An estimate, not advice.",
        "method": "GET", "path": "/api/expenses/summary",
    },
    {
        "name": "bc_ad_ledger",
        "summary": "Advertising spend and what it returned, per platform "
                   "and per campaign, across every connected ad account.",
        "method": "GET", "path": "/api/ads",
    },

    # ---------- who is talking to us ----------
    {
        "name": "bc_tickets",
        "summary": "Support tickets: what is open, how old, and who has "
                   "it.",
        "method": "GET", "path": "/api/tickets",
    },
    {
        "name": "bc_outreach",
        "summary": "The sales pipeline: leads and accounts by stage, with "
                   "what was promised next and when.",
        "method": "GET", "path": "/api/outreach",
    },
    {
        "name": "bc_listings",
        "summary": "The public listing this business shows on Google and "
                   "Yelp, and every review pulled in, answered or not.",
        "method": "GET", "path": "/api/listings",
    },
    {
        "name": "bc_forms_and_gifts",
        "summary": "Form responses waiting to be turned into somebody, "
                   "and the gifts received.",
        "method": "GET", "path": "/api/intake",
    },
    {
        "name": "bc_notifications",
        "summary": "What the system has flagged for attention.",
        "method": "GET", "path": "/api/notifications",
    },

    # ---------- stock and supply ----------
    {
        "name": "bc_suppliers",
        "summary": "Suppliers, materials, purchase orders and production "
                   "runs.",
        "method": "GET", "path": "/api/supply",
    },
    {
        "name": "bc_presentations",
        "summary": "Decks, recordings and uploads, and which class each "
                   "is attached to.",
        "method": "GET", "path": "/api/presentations",
    },

    # ---------- the books, the bank, the register ----------
    {
        "name": "bc_trial_balance",
        "summary": "The ledger's trial balance and this year's income "
                   "statement and balance sheet. Unlike the profit and "
                   "loss above, this comes from double-entry books that "
                   "must balance — if 'balanced' is false, nothing derived "
                   "from it should be quoted.",
        "method": "GET", "path": "/api/accounting",
    },
    {
        "name": "bc_account_ledger",
        "summary": "Every entry that touched one account, with a running "
                   "balance. How a difference is found rather than merely "
                   "noticed.",
        "method": "GET", "path": "/api/accounting/ledger/{code}",
        "path_params": {"code": {"type": "string",
                                 "description": "four-digit account code"}},
        "required": ["code"],
    },
    {
        "name": "bc_cash_position",
        "summary": "What is in each account, what is set aside, what is "
                   "free, the holdings, and the runway. Runway is "
                   "arithmetic on the past — quote it as a projection.",
        "method": "GET", "path": "/api/treasury",
    },
    {
        "name": "bc_legal_register",
        "summary": "Contracts, policies, licences and filings with the "
                   "dates that matter, plus the diary of what falls due. "
                   "It records decisions somebody made; it is not advice.",
        "method": "GET", "path": "/api/legal",
    },
    {
        "name": "bc_automations",
        "summary": "The business's own rules, what each listens for, and "
                   "how its recent runs went.",
        "method": "GET", "path": "/api/automation",
    },

    # ---------- writing: additive, reversible, off by default ----------
    {
        "name": "bc_add_ticket",
        "summary": "Open a support ticket. Somebody will read it; opening "
                   "one in error costs them the read.",
        "method": "POST", "path": "/api/tickets", "write": True,
        "body": {"title": {"type": "string",
                           "description": "one line: what this is about"},
                 "body": {"type": "string", "description": "the detail"},
                 "priority": {"type": "string",
                              "description": "how urgent, as this business words it"}},
        "required": ["title"],
    },
    {
        "name": "bc_note_on_student",
        "summary": "Write a dated line on a student's record: a note, a "
                   "milestone, a concern, something they achieved. It is "
                   "dated when the thing happened, not when you file it, "
                   "and staff can delete it.",
        "method": "POST", "path": "/api/students/{uid}/log", "write": True,
        "path_params": {"uid": {"type": "integer",
                                "description": "the student's account id"}},
        "body": {"kind": {"type": "string",
                          "enum": ["note", "milestone", "concern",
                                   "achievement"],
                          "description": "what sort of line this is"},
                 "title": {"type": "string", "description": "the line itself"},
                 "body": {"type": "string", "description": "any detail"},
                 "at": {"type": "number",
                        "description": "unix seconds it happened; omit for now"}},
        "required": ["uid", "title"],
    },
    {
        "name": "bc_log_expense",
        "summary": "File an expense. It lands PENDING and a human approves "
                   "it, so this proposes a cost rather than incurring one.",
        "method": "POST", "path": "/api/expenses", "write": True,
        "body": {"category": {"type": "string",
                              "description": "a category code from bc_expenses"},
                 "amount_cents": {"type": "integer",
                                  "description": "the amount, in cents"},
                 "vendor": {"type": "string", "description": "who was paid"},
                 "note": {"type": "string", "description": "what it was for"},
                 "spent_at": {"type": "number",
                              "description": "unix seconds; omit for now"}},
        "required": ["category", "amount_cents"],
    },
    {
        "name": "bc_outreach_note",
        "summary": "Add a dated note to a pipeline row and optionally move "
                   "what happens next. The stage history is kept, so a "
                   "wrong move is visible and reversible.",
        "method": "POST", "path": "/api/outreach/{oid}/update", "write": True,
        "path_params": {"oid": {"type": "integer",
                                "description": "the pipeline row id"}},
        "body": {"note": {"type": "string", "description": "what happened"},
                 "next_action": {"type": "string",
                                 "description": "what is promised next"}},
        "required": ["oid", "note"],
    },
    {
        "name": "bc_move_applicant",
        "summary": "Move an applicant between stages, or add notes to "
                   "them. Cannot hire: that opens a real account with a "
                   "role, which is a person's decision.",
        "method": "PATCH", "path": "/api/hiring/applicants/{aid}",
        "write": True,
        "path_params": {"aid": {"type": "integer",
                                "description": "the applicant id"}},
        "body": {"stage": {"type": "string",
                           "enum": ["new", "screen", "interview", "offer",
                                    "declined"],
                           "description": "the stage to move them to"},
                 "notes": {"type": "string",
                           "description": "replaces the notes on them"}},
        "required": ["aid"],
    },
    {
        "name": "bc_log_ad_spend",
        "summary": "Type a row into the ad ledger for a platform with no "
                   "API, such as Twitch or a print run. Records what was "
                   "spent; spends nothing.",
        "method": "POST", "path": "/api/ads/manual", "write": True,
        "body": {"platform": {"type": "string",
                              "description": "a platform key from bc_ad_ledger"},
                 "name": {"type": "string", "description": "the campaign"},
                 "spend_cents": {"type": "integer", "description": "in cents"},
                 "impressions": {"type": "integer"},
                 "clicks": {"type": "integer"},
                 "results": {"type": "integer"}},
        "required": ["platform", "name"],
    },
]

# Left off on purpose, with the reason. Irreversible, public, or it moves
# money — the three kinds of act that should keep a person in the loop
# even when the operator trusts the agent. Written down because an empty
# space explains nothing to whoever wonders why a route is missing.
EXCLUDED = {
    "POST /api/orders": "places a real order against real stock",
    "POST /api/orders/{oid}/confirm-payment": "moves money",
    "POST /api/expenses/{eid}/decide": "approving a cost is the approval "
                                       "the pending state exists to get",
    "POST /api/hours/approve": "signs off pay",
    "POST /api/hiring/applicants/{aid}/hire": "opens an account with a "
                                              "role and a first week",
    "POST /api/listings/reviews/{rid}/reply": "publishes in the "
                                              "business's name, to a "
                                              "customer, on Google",
    "POST /api/listings/ask": "emails a customer",
    "POST /api/marketplaces/{name}/push": "republishes the menu to a "
                                          "delivery platform",
    "POST /api/marketplaces/{name}/status": "pauses or resumes taking "
                                            "delivery orders",
    "POST /api/ads/{platform}/expense": "files a cost as already approved",
    "POST /api/accounting/journals": "posting to the books is bookkeeping, "
                                     "and a wrong entry is corrected by a "
                                     "reversal somebody has to understand",
    "POST /api/accounting/periods/{pid}/close": "closes a year against "
                                                "further posting",
    "POST /api/treasury/transfer": "moves money between real accounts",
    "POST /api/automation/rules": "a rule is a standing instruction — an "
                                  "agent writing one is an agent granting "
                                  "itself an action it was not given",
    "DELETE *": "nothing here deletes",
    "POST /api/admin/*": "settings, staff, permissions and keys",
    "/api/store/admin/*": "the shop front's own admin",
}


def by_name() -> dict:
    return {t["name"]: t for t in TOOLS}


def schema_for(tool: dict) -> dict:
    """The JSON Schema an MCP client validates a call against."""
    props = {}
    for group in ("path_params", "query", "body"):
        props.update(tool.get(group) or {})
    return {"type": "object", "properties": props,
            "required": list(tool.get("required") or [])}


def description_for(tool: dict) -> str:
    """What the model reads. The write warning is part of the text rather
    than a flag, because a flag is something the client may or may not
    show and the sentence is always read."""
    text = tool["summary"]
    if tool.get("write"):
        text += (" WRITES: this changes the business's records. It is "
                 "additive and a person can undo it, but say what you are "
                 "about to do before you do it.")
    return text
