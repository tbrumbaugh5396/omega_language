# The API — the machine door

Everything the UI does travels through the same JSON API, so everything
the UI can do, a script can do — there is no second, lesser path. This
page is the door policy; the full interactive reference is served live at
**`/docs`** on every install (OpenAPI, generated from the code, so it
cannot drift).

## Keys

The **API & data platform** capability ($30, price book §3) sells scoped
keys, and they work like this:

- **Minted** on ops → Integrations → *API keys*, by an admin. The secret
  (`bck_…`) is shown **once** and stored hashed; the list identifies keys
  by name and prefix, never by secret.
- **Bound to an account.** A key acts AS the account it is bound to,
  through every permission check the app already enforces — one
  authorization model, not two. Bind narrow: a key bound to a plain
  account can only ever do what that account could.
- **Scoped.** `read` keys are refused every mutation at the front door
  (one wall, not two hundred doors remembering); `write` keys do whatever
  their account may.
- **Revocable, instantly.** Revocation is the key's lifecycle — machine
  keys never slide-expire the way human sessions do, and `last_used`
  makes a stale key visible before it is a mystery.
- **Entitlement outranks the secret.** A plan that drops the api
  capability makes every key stop working mid-flight; minting 404s.

## Using one

```sh
curl -H "Authorization: Bearer bck_..." https://shop.yourbrand.com/api/orders
```

Tenancy rides the hostname as always — a key belongs to the tenant whose
database minted it, and answers on that tenant's hosts.

## What else is machine-shaped

- **Webhooks** (Integrations) push events out; **exports** (CSV, data
  rights bundles, client binders) pull documents whole.
- The **fleet/node API** (`X-Fleet-Key`) is the provider's own machine
  door for shipping tenants and code between machines.
- `/docs` and `/openapi.json` describe every route, live.

## Conventions and honest limits

Routes are nouns under `/api/…`; errors carry a human `detail`; audit
records every mutating call. Pagination is ad-hoc (`LIMIT`-shaped) —
fine at present scale, the first thing to regularise when a sync job
needs to walk a big table. Rate limiting exists on sensitive routes; a
shared-tenant fairness pass is on the list before untrusted third-party
keys are common.
