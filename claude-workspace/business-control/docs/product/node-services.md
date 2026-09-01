# Node services — daemons the machine shares

A node service is a daemon installed once per machine and shared by every
tenant living on it: translation today; an SFU with recording egress, and
(if the tooling direction firms up) a git forge, next. It is how the
platform grows capabilities that need real software running beside it —
without a per-tenant install, a per-tenant bill, or a tenant's data
leaving the box.

## The manifest

`data/node_services.json`, beside the fleet registry and outside every
tenant directory — a service belongs to the machine the way a disk does:

```json
{"translate": {"url": "http://127.0.0.1:5000", "key": ""}}
```

`erp/backend/services.py` reads it (mtime-cached), probes health live
(never stored — a stored "healthy" is a lie waiting for a restart), and
reports a `{name: healthy}` summary that rides the node's ping. The
Platform tab wears it as pills on the local node's card; **Check** on a
worker asks that machine live.

## The resolution rule

Everywhere a service is consumed, in this order:

1. **The tenant's own config wins** — a tenant paying for its own
   provider keeps it (`translate_url`/`translate_key`).
2. **The node's manifest is the floor** — nothing configured, the
   machine's shared daemon answers.
3. **Absence degrades to exactly the pre-services behavior** — for
   translation, the offline glossary and its honest "not found".

Every answer carries `via` ("remote" / "node service" / "local
glossary"), so nobody guesses where a translation came from.

## Installing a service

Installers ship in `scripts/` — and therefore inside every app bundle,
so a worker node can grow the same services its provider has:

```sh
sudo bash scripts/install_translate.sh --langs en,es
```

That stands LibreTranslate up in its own venv under systemd, bound to
localhost, and writes the manifest line. First run downloads the
language models (minutes, once); after that the machine translates
offline — a school's students' words never leave it. On a machine
without systemd (a dev Mac), run LibreTranslate however you like and
write the manifest line by hand — `services.declare("translate", url)`
or one line of JSON.

## What this is not

Not placement policy: a tenant whose plan includes Voice still works on
a node without the daemon (the glossary floor is the product's honest
default), so `pick_node` does not gate on services — the Platform tab
makes the gap visible instead, and the fix is one installer run on that
node. And not per-tenant isolation: the daemon is stateless and shared;
per-tenant rate limits at the app layer are the fence, the same one the
API already has.
