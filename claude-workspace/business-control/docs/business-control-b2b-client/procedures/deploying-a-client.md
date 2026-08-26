# Procedure — deploying a client

**When:** the build is signed off at round 2 and the final invoice is paid.

**Takes:** two weeks of preparation, two hours on the day.

---

Full detail is in the [roadmap](../roadmap.md#deployment) and the technical runbook is [`docs/DEPLOY.md`](../../product/DEPLOY.md). 
This is the short version and the order it goes in.

## Two weeks out

- [ ] Server in **the client's account**, on their card
- [ ] DNS access proven by logging in, not promised
- [ ] **TTL lowered to 300s** — the single most valuable thing on this page
- [ ] Payment live keys tested with a real card, then refunded
- [ ] Email domain verified: SPF, DKIM, DMARC

## One week out

- [ ] Old site backed up **and restore-tested**
- [ ] DNS zone screenshotted whole
- [ ] Redirect map written from the URLs that have traffic
- [ ] `require_passwords: true`, admin key rotated, firewall to 22/80/443
- [ ] Launch window agreed — not a Friday, not before you travel

## On the day

1. Final backup of the old site
2. Deploy; confirm it answers on the server's own address
3. Change the A record; watch propagation and touch nothing else
4. HTTPS green
5. Walk every redirect
6. **Real order, real card, then refund it**
7. Sitemap submitted, analytics recording
8. TTL back to normal

## The week after

- [ ] A backup restored, not just taken
- [ ] Search Console clean
- [ ] Logs read daily for a week
- [ ] QR codes reprinted with the public URL

> **Leave the old site up and untouched for a fortnight.** Rollback is a DNS
> change back, and only if you didn't tidy it away on launch day.

---

**Done when:** live, HTTPS, an order placed and refunded, a backup restored, and the client told in writing that the 30 days of support has started.
