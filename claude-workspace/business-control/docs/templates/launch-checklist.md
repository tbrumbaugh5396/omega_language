# Launch checklist — [PROJECT]

**Launch date:** [DATE] · **Time:** [TIME] · **Run by:** [YOU]

**Never launch on a Friday.** Never launch the day before you travel. If
something breaks you want a working day in front of you, not a weekend of
missed calls.

---

## Before launch day

### Money and permission
- [ ] **Final invoice paid** — do not launch on a promise
- [ ] Written approval to launch from the named approver

### Safety
- [ ] **Full backup of the existing site taken and verified** — files and
      database, downloaded somewhere you control
- [ ] Backup restore tested, or at least the archive opened
- [ ] Current DNS records recorded — screenshot the whole zone
- [ ] Rollback plan written down: [WHAT YOU'D DO]

> You'll need the backup roughly once every twenty projects. On that day it's
> the difference between an inconvenience and a catastrophe.

### Content
- [ ] Every page final and proofread
- [ ] No placeholder text anywhere — search for "lorem", "TODO", "TBC", "XXX"
- [ ] Contact details correct **and tested**
- [ ] Prices correct
- [ ] Copyright year correct
- [ ] Legal pages in place: privacy, terms, cookies

### Function
- [ ] Every form submitted and the email received at the right address
- [ ] Form spam protection on
- [ ] Auto-responders correct
- [ ] Every menu and footer link tested
- [ ] Social links go to the right accounts
- [ ] Search works, if present
- [ ] E-commerce: test purchase completed end to end, then refunded
- [ ] Integrations tested with real data

### Technical
- [ ] SSL certificate ready
- [ ] 301 redirects mapped from every old URL with traffic or links
- [ ] 404 page exists and is useful
- [ ] `robots.txt` correct — **check it isn't still blocking everything**
- [ ] `sitemap.xml` generated
- [ ] Canonical URLs correct
- [ ] **Staging blocked from indexing** — and the block removed from
      production
- [ ] Favicon and app icons
- [ ] Open Graph tags — test how a link looks when shared
- [ ] Structured data validated

> The single most common launch error in the industry: shipping with
> `noindex` still on from staging. Check it twice.

### Quality
- [ ] Chrome, Safari, Firefox, Edge — current and previous
- [ ] iPhone and Android, real devices if possible
- [ ] Tablet
- [ ] Lighthouse: performance [N], accessibility [N], SEO [N]
- [ ] Keyboard navigation works
- [ ] Colour contrast passes
- [ ] All images have alt text
- [ ] Images compressed — nothing over [300]KB without reason

### Analytics
- [ ] Analytics installed and tested in real time
- [ ] Goals / conversions configured
- [ ] Search Console verified, sitemap ready to submit
- [ ] Any advertising pixels installed
- [ ] Consent banner working, if required

---

## Launch day

1. [ ] Final backup of the old site
2. [ ] Confirm the client is ready — they may want to time an announcement
3. [ ] Lower DNS TTL a day ahead if you remembered; if not, expect slower
       propagation
4. [ ] **Check where email is hosted before touching DNS** — this is how
       people take a company's email down
5. [ ] Switch DNS / point the domain
6. [ ] Wait for propagation
7. [ ] Force SSL, confirm the padlock
8. [ ] `www` and non-`www` both resolve correctly
9. [ ] Old URLs redirect properly — spot-check ten
10. [ ] Remove `noindex`
11. [ ] Submit the sitemap to Search Console
12. [ ] Confirm analytics is recording live traffic
13. [ ] **Send a test email through a form on the live site**
14. [ ] Tell the client it's live

---

## Within 24 hours

- [ ] Full pass on the live site, not staging
- [ ] Forms tested again on production
- [ ] Analytics recording
- [ ] No console errors
- [ ] Uptime monitoring on
- [ ] Client has the handover document
- [ ] Watch for anything odd

## Within a week

- [ ] Search Console: no coverage errors
- [ ] Redirects working — check for 404 spikes
- [ ] Client trained and comfortable
- [ ] Support window explained: ends [DATE]
- [ ] Care plan discussed
- [ ] Portfolio updated
- [ ] Testimonial requested

---

## If something goes wrong

**Site down:** revert DNS to the previous records — you screenshotted them.
Tell the client immediately, before they notice.

**Email down:** almost certainly an MX record. Restore the old MX values
first, diagnose second.

**Something looks broken but works:** don't panic-fix on production. Reproduce
on staging.

**Client panics about something small:** acknowledge, give a time, fix it.
Launch day nerves are normal and mostly not about the thing they mentioned.

---

**Launched by:** ______________ **Date/time:** ______________
**Notes:** ______________
