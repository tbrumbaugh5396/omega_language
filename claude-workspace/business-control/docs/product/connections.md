# Connections: the second wave

The first eleven connections (Slack, Trello, Pipedrive, Dropbox, QuickBooks,
Canva, DocuSign, three Google consents, LaceUp) are one table in
`src/erp/backend/integrations.py` and one screen. The second wave keeps
the table and adds a **working screen per family**, because a person
setting up TikTok is on the Advertising screen, not in a settings list.
Every connection is still on *All connections*; it is set up where it
is used.

| Family | Screen (rail group) | Providers | Module |
|---|---|---|---|
| Intake | Forms, gifts & results (Grow) | Google Forms, Network for Good, GED Manager, NorthStar | `intake.py` |
| Advertising | Advertising (Grow) | Meta (Facebook & Instagram), Google Ads (YouTube & Search), TikTok, LinkedIn, X, Reddit, Snapchat; Twitch typed | `ads.py` |
| Hiring | Hiring (Team) | Indeed, ZipRecruiter, LinkedIn Jobs, Greenhouse, Workable | `hiring.py` |
| Delivery | Delivery apps (Sell) | Uber Eats, DoorDash | `marketplaces.py` |
| Listings | Listings & reviews (Grow) | Google Business Profile, Yelp | `listings.py` |

## What is honest about each

**Advertising is read, never written.** Each platform's campaigns, spend,
impressions and clicks for the last thirty days come into one ledger
(`ad_campaigns`), upserted by the platform's campaign id so a pull is safe
to repeat. Nothing here creates a campaign or spends a cent. A platform's
spend can be filed as an approved expense in the *Advertising* category
with one button, so the tax summary already knows. **Twitch** ads are
bought through Amazon Ads, which has no self-serve API: Twitch is a column
you type, and the screen says so. So is "Everything else" (print, radio, a
sign).

Google Ads needs a developer token and a customer id besides the OAuth
consent; Meta needs an ad account id; the rest need their account id.
These are *settings after connecting*, saved on the card. A secret one (the
developer token) goes into credentials and is never read back.

**Job boards take a feed, not a posting.** Indeed, ZipRecruiter and
LinkedIn each ingest the XML at `/jobs.xml` (Indeed's format, which the
others adopted) and post applications to `/api/inbound/<board>` with the
key issued on the card. Nobody offers a write API for postings. The public
page at `/jobs` lists open postings and takes applications with a CV,
which goes through the blob store. Greenhouse and Workable, which are
applicant-tracking systems with real APIs, *pull* candidates and fold their
stage names into ours (new, screen, interview, offer, hired, declined).
**Hiring** somebody opens their account with the chosen role and writes a
six-line onboarding list (contract, paperwork, PIN and badge, rota, tools,
check-in) that the office ticks.

**Delivery apps get a copy of the menu.** A product ticked as "on the
menu" is pushed, with its price and our SKU as its id, as the store's Uber
Eats menu (whole-menu `PUT`) or DoorDash menu (`POST`), and pushed again
whenever a product changes (`product.created` / `product.updated` events).
Orders they send to `/api/inbound/<app>?key=…` are matched by SKU, placed
through the same path a LaceUp order takes, and accepted (Uber) or
confirmed (DoorDash) back. The store can be paused and resumed. Both are
**partner APIs**: the platform approves the integration before issuing a
credential, and their endpoints move by version, which is why every URL is
in `ENDPOINTS` at the top of `marketplaces.py` — check them against the
partner portal on first connect. DoorDash's JWT (HS256, `dd-ver`) is minted
in `dd_jwt`.

**Google can be read and written; Yelp only read.** The profile
(`business_listing`) is pulled from Google Business Profile and pushed back
for the fields Google lets an API change without re-verification (phone,
website, hours, description; not the name or address). Google reviews pull
into `reviews_inbox` and replies post from here. Yelp's public API returns
the listing and three review excerpts and takes no reply and no edit, so
Yelp's copy is shown *beside* ours and each review links to its page.
*Ask a customer for a review* emails the place-id review link (or the Maps
link) through the same logged mailer as everything else.

**Intake is records, not events.** Google Forms responses are pulled by
form id (question ids turned back into titles) or pushed by the Apps
Script snippet on the screen; each is kept once and can become an enquiry
on the sales board, a student (answers onto their profile, the form on
their timeline) or a customer. Network for Good gifts arrive by webhook or
by CSV; each donor becomes a `donor` in the address book. **GED Manager**
and **NorthStar** publish no API: their CSV score reports import, columns
read by *meaning* (email, subject, score, date) rather than by fixed
heading, matched to a student by email then by exact name, a pass logged
as an achievement and a miss as a milestone. A row that matches nobody is
kept unmatched until the office says whose it is.

## Machinery the wave added

- `PROVIDERS[name]["family"]`, `inbound: True` (a provider that connects
  outbound and also pushes to us gets a key), `settings_fields` and
  `POST /api/admin/integrations/{name}/settings`.
- Registries a family module fills at import: `CHECKS` (credential check),
  `VERIFIERS` (OAuth test), `INBOUND` (what a POST means), `IMPORTS` (what a
  CSV means), `DELIVERS` (what an event does). `/api/inbound/{name}` and
  `/api/admin/integrations/{name}/import` dispatch to them before the
  LaceUp order fallback.
- OAuth: `app_for()` shares one registered Google app across every Google
  consent (`oauth.app_group`); `token_auth: "body"` for providers (Meta,
  LinkedIn, Snapchat) that want the client secret as a form field rather
  than HTTP Basic; `pkce: True` for X.
- The ops rail is eight groups by what a person is doing (Sell, Stock &
  supply, Work, Teach, Grow, Team, Company, Connections); the wave adds no
  rail entries of its own.

## Not done, on purpose

- No connection has been exercised against a live account. Each check and
  pull is written to the platform's documented endpoint and tested against
  a stub that answers in that shape; the first real connect is where a
  moved endpoint shows up, and the message will say what the platform said.
- Twitch, print and the like are typed. There is no API to pull them from.
- Yelp replies and edits happen on Yelp.
- Postings are not written to any board; the feed is read by them.
