# Delivery, deployment & setup roadmap

**Internal, with client-facing extracts.** 
The [packages and process document](templates/02-consultation/packages-and-process.md) tells a client *what* happens and *when*. 
This tells you *how* — what physically gets built, what gets handed over, in what format, and how the thing actually gets onto the internet in the client's name.

Read it once before your first deployment. 
Then use the checklists.

---

## The shape of a delivery

| Phase | Weeks | What exists at the end | Who sees it |
|---|---|---|---|
| 0 · Setup | 0 | A running instance on your infrastructure, seeded with their real products | You |
| 1 · Discover | 1 | Signed requirements | Both |
| 2 · Design | 2–4 | The storefront wearing their brand, on a staging URL | Both |
| 3 · Build | 4–10 | Every module they bought, their data migrated in | Both |
| 4 · Launch | 11–12 | Live on their domain, in their accounts | Both |
| 5 · Handover | 12 | They can run it without you | Both |
| 6 · Aftercare | ongoing | Backups verified, updates applied | You |

**The staging URL goes up in week 2 and never comes down.** 
Clients who watch a thing fill up week by week ask for less and trust more than clients who wait twelve weeks for a reveal. 
It also means "can you show me where we are" is answered by a link rather than by an afternoon of screenshots.

---

## Phase 0 — Setup, before the client sees anything

One instance per client. 
Never share a database between two of them, and never develop against the instance that will become production.

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python3 scripts/make_icons.py
PYTHONPATH=src ./.venv/bin/python3 tools/seed_catalog.py
```

| Step | Why it matters |
|---|---|
| Fresh checkout per client | Their data never touches another client's |
| `data/config.json` created and **backed up** | It holds the admin key; losing it locks you out of your own build |
| Seed the real range, not lorem products | A demo full of "Product 1" reads as unfinished and invites redesign |
| Their brand tokens set in the theme | The first thing they see should already look like them |
| A staging domain that isn't guessable | `client-x-staging.[yourdomain]`, `noindex` on, HTTP auth if the brand is unannounced |

> **`data/config.json` is backup-critical and it is not in version control.**
> It carries the admin key, the SMTP credentials and the payment keys. Back it
> up somewhere you control the moment it's created, and again after every
> change. Losing it mid-project is recoverable but expensive; losing it after
> handover is the client's problem and therefore yours.

---

## What they actually receive

Everything below is a deliverable with a format, not a promise. 
Write the formats into the proposal so "can I have the files" is answered before it's asked.

### At launch

| Deliverable | Format | Where it lands |
|---|---|---|
| The live system | On their domain, HTTPS | Their hosting account |
| Source code | Git repository | Their organisation, not yours |
| Database | SQLite file + a verified restore | Their backup location |
| `data/config.json` | Encrypted file or a password manager entry | Their password manager |
| Admin credentials | Their own account, password set by them | Never emailed in plain text |
| Design files | The originals — `.fig`, `.ai`, `.svg` | Their drive |
| Brand assets | Logo in `.svg` + `.png` at 3 sizes, favicon set, app icons | Their drive |
| Product photography | Originals and web derivatives, named consistently | Their drive |
| The hook film, if bought | `.mov` master + `.mp4` web + a poster frame | Their drive |
| Handover document | Filled-in [handover template](templates/10-handover/handover-template.md) | PDF and editable |
| Training recording | Video, ~30–60 min | Their drive |

### Accounts transferred, not shared

| Account | Transfer method |
|---|---|
| Domain registrar | Their account from the start, ideally — otherwise a registrar transfer, which takes 5–7 days |
| Hosting / VPS | Their billing, their card |
| Payment processor | **Always theirs from day one.** You never touch the money |
| Email sending (SMTP) | Their account, their sending domain verified |
| Analytics | Their Google account, you added as a user |
| Any integration | Their workspace, their tokens |

> **Start the domain and payment accounts in the client's name.** A domain
> registered on your card is a five-day transfer and an awkward conversation at
> exactly the moment you want a testimonial. A payment account in your name is
> worse — it makes you a party to their money, which is a liability you are not
> insured for.

---

## Deployment

The technical runbook is [`docs/DEPLOY.md`](../product/DEPLOY.md) — server, Caddy,
systemd, config hardening, backups. 
Don't duplicate it here; it's the source of truth and it's kept current with the code.

What that document doesn't cover is the *sequencing* around it, which is where launches go wrong.

### Two weeks before

- [ ] Server provisioned **in the client's account**, billed to their card
- [ ] Domain and DNS access confirmed — actually logged in, not promised
- [ ] TTL on the existing DNS records lowered to 300s
- [ ] Staging deployed to production-shaped infrastructure, so launch day is a DNS change and nothing else
- [ ] Payment processor live keys tested with a real transaction, then refunded
- [ ] Email sending domain verified — SPF, DKIM, DMARC

> **Lower the TTL two weeks out.** If you don't, a bad cutover takes up to 48
> hours to undo instead of five minutes. It is one setting and it is the
> difference between a hiccup and a very long day.

### One week before

- [ ] Full backup of whatever exists today, downloaded and **restore-tested**
- [ ] Current DNS zone screenshotted in full
- [ ] Redirect map written, from the old URLs with traffic to the new ones
- [ ] Rollback plan written down in one paragraph
- [ ] `require_passwords: true`, admin key rotated, firewall to 22/80/443
- [ ] Launch window agreed — **never a Friday**

### Launch day

1. Final backup of the old site.
2. Deploy the current build; confirm it answers on the server's own address.
3. Change the DNS A record. Watch propagation; don't touch anything else.
4. Certificate issued and HTTPS green.
5. Walk the redirect map — every old URL lands somewhere sensible.
6. **Place a real order with a real card.** Refund it. This is the only proof that matters.
7. Submit the sitemap; confirm analytics is recording.
8. Raise the TTL back to normal.

### The week after

- [ ] Nightly backup ran, and you restored one to check
- [ ] Search Console clean of crawl errors
- [ ] Watch the logs daily for a week
- [ ] Reprint any QR codes — they now encode the public URL, not the LAN one

---

## Setup and training

Deployment puts it on the internet. Setup makes it theirs.

| Step | Who | Notes |
|---|---|---|
| Owner account created, password set **by them** | Client | You should never know it |
| Staff accounts created with real roles | Both | Use the smallest permission that works |
| Permission boundaries confirmed | Client | Walk the "who must not see what" answers from the consultation |
| Integrations connected with **their** tokens | Both | Never your workspace, never your API key |
| Backup schedule live and verified | You | A backup nobody has restored is a rumour |
| Training session, recorded | Both | 30–60 min, the recording is a deliverable |
| 30 days of support begins | You | Say when it ends, in writing, on the day it starts |

### Training — cover exactly these, in this order

1. Adding and editing a product, including the photo.
2. Taking, fulfilling and refunding an order.
3. Editing a page and publishing it.
4. Adding a staff member and choosing what they can see.
5. Where the numbers are, and which one to look at on a Monday.
6. What to do when something breaks — who to call, what to send.

> Record it. Staff turn over, and the second person to hold the job will
> otherwise call you for free forever. The recording also converts care plans:
> it makes plain how much there is to keep an eye on.

---

## Aftercare

| Cadence | What | Plan |
|---|---|---|
| Nightly | Backup runs | All |
| Weekly | Backup restore-tested, uptime and error log reviewed | All |
| Monthly | Dependency and security updates, performance check | All |
| Monthly | Included change hours — use them or they lapse | Standard, Priority |
| Quarterly | Analytics review with the client | Priority |
| Annually | Domain and certificate renewals, a look at what's grown | All |

**The renewal conversation happens in month ten, not month twelve.** A care plan that lapses silently is a client you've lost without either of you deciding to.

---

## When it goes wrong

| Symptom | First thing to check |
|---|---|
| Site unreachable after DNS change | Propagation, then the certificate, then the service is actually running |
| Certificate won't issue | Port 80 reachable, and DNS pointing at the right server |
| Orders arriving but no email | SMTP credentials, then the sending domain's SPF/DKIM |
| Payments failing | Live keys, not test keys — and `public_base_url` set to the real domain |
| Integration silently stopped | Token expired or revoked; check the audit log for when it last worked |
| Everything slow | Check backups aren't running in the middle of the day |

**Rollback is a DNS change back.** 
That is the whole reason the old site stays up and untouched for a fortnight after launch. 
Don't delete it on launch day because it looks tidy.
