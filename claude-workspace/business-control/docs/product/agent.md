# Wiring an agent in

Business Control speaks [Model Context
Protocol](https://modelcontextprotocol.io), so Claude and anything else
that speaks MCP can read the business and, if you let it, write to it.

```bash
PYTHONPATH=src BC_MCP_KEY=bck_… python3 -m mcp_server
```

It talks JSON-RPC over stdin and stdout, which is what an MCP client
launches and connects to. There is nothing to install: the protocol is a
hundred lines and it is written out in `src/mcp_server/server.py` rather
than pulled in, so trying this costs you a key and a config block.

## Setting it up

**Mint a key.** Ops, Integrations, API keys, *Mint a key*. Choose the
account it acts as, and choose narrowly — see below. The secret shows
once.

**Point a client at it.** For Claude Desktop, in
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "business-control": {
      "command": "python3",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/business-control/src",
        "BC_MCP_URL": "https://your-install.example",
        "BC_MCP_HOST": "yourtenant.example",
        "BC_MCP_KEY": "bck_…"
      }
    }
  }
}
```

| Variable | What it does |
|---|---|
| `BC_MCP_URL` | Where the install answers. Default `http://127.0.0.1:8860` |
| `BC_MCP_HOST` | Host header, when one address serves many tenants |
| `BC_MCP_KEY` | The key. Without it every call is refused |
| `BC_MCP_WRITES` | `1` to offer the tools that change records. Off by default |

## What it can do

Forty-one read tools and seven write tools, chosen by hand from the
install's several hundred routes and listed in `src/mcp_server/tools.py`.
Reading covers the catalogue, orders, customers, stock, the numbers, the
classroom, students, hours and the rota, expenses and the tax summary, the
ad ledger, hiring, listings and reviews, tickets, the pipeline, suppliers,
the books, the bank, the legal diary, invoices, payroll, the policy
register and its timeline for a place, and the team's ideas graph.

Writing is off unless you turn it on, and then only for things that are
additive and reversible by somebody who did not expect them: a note on a
student, a ticket, a pipeline note, a pending expense, an applicant's
stage, a typed ad-spend row, a note in the ideas graph.

## What it deliberately cannot do

Even with writes on, the agent cannot place an order, take a payment,
approve an expense or a timesheet, hire somebody, reply to a Google
review, email a customer, republish a delivery menu, change settings or
permissions, or delete anything.

The test for inclusion was one question asked of every route: what
happens if the model is confidently wrong? A wrong note is deleted by
whoever reads it. A wrong refund is a phone call to a bank. Everything in
the second category stays with a person, and the omissions are written
down in `EXCLUDED` in the tools file rather than left as gaps.

## Three walls, not one

The tool list is the weakest of the three and should not be relied on
alone.

**The key is bound to an account.** Every call lands in the same
permission check the screens use, so a key bound to a shop assistant sees
what that assistant sees. This is the real control: an agent cannot reach
what its account cannot reach, whatever the tool list says and whatever
the model decides it wants. Bind narrowly.

**The key is scoped.** A `read` key has mutations refused at the front
door, so a read key makes every write tool fail even if the server was
started with `BC_MCP_WRITES=1`.

**The list is short.** Which stops the model from *attempting* things,
and keeps its attention on the tools that matter.

All three are live: entitlement is read on each request, so revoking a
key or a capability stops an agent mid-conversation.

## What it leaves behind

Every call is a normal API request, so the audit log records it like any
other. A key stamps `last_used_at`, which is how a forgotten integration
becomes visible rather than mysterious.

## Known limits

The catalogue is checked against the install's own OpenAPI document by
the test suite, so a tool cannot point at a route that does not exist or
send a field a route would silently drop. What is not checked is
judgement: whether these are the right forty-eight verbs is a question
answered by using it. Add to `TOOLS` and the guard picks the new entry up.
