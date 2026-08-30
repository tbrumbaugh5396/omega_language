"""Optional Stripe Checkout. No secret key configured -> card payments are
off and orders fall back to pay-on-delivery (customers) / on-terms
(distributors). With a key, checkout happens on Stripe's hosted page and we
verify the session server-side on return — no card data ever touches us."""
import httpx

API = "https://api.stripe.com/v1"


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("stripe_secret_key"))


def verify_key(key: str) -> tuple[bool, str]:
    """Ask Stripe whether this key works, before anyone relies on it.

    Saving an unverified key means the first person to find out it's wrong is
    a customer at the checkout, which is the worst possible place to discover
    a typo.
    """
    try:
        r = httpx.get(f"{API}/balance", auth=(key, ""), timeout=15)
    except Exception as e:                      # noqa: BLE001
        return False, f"couldn't reach Stripe ({str(e)[:80]})"
    if r.status_code == 200:
        return True, "ok"
    try:
        return False, r.json().get("error", {}).get("message", r.text[:120])
    except Exception:
        return False, r.text[:120]


def create_checkout(cfg: dict, order_id: int, items: list[dict],
                    extra_cents: int, base_url: str) -> dict | None:
    """items: [{name, unit_cents, qty}]; extra_cents covers tax+shipping.
    Returns {id, url} or None when Stripe is not configured."""
    if not enabled(cfg):
        return None
    data = {
        "mode": "payment",
        "success_url": f"{base_url}/?paid={order_id}"
                       "&sid={CHECKOUT_SESSION_ID}",
        "cancel_url": f"{base_url}/?cancelled={order_id}",
        "client_reference_id": str(order_id),
    }
    lines = list(items)
    if extra_cents > 0:
        lines.append({"name": "Tax & shipping", "unit_cents": extra_cents,
                      "qty": 1})
    for i, it in enumerate(lines):
        data[f"line_items[{i}][quantity]"] = str(it["qty"])
        data[f"line_items[{i}][price_data][currency]"] = "usd"
        data[f"line_items[{i}][price_data][unit_amount]"] = str(it["unit_cents"])
        data[f"line_items[{i}][price_data][product_data][name]"] = it["name"]
    r = httpx.post(f"{API}/checkout/sessions", data=data,
                   auth=(cfg["stripe_secret_key"], ""), timeout=20)
    r.raise_for_status()
    d = r.json()
    return {"id": d["id"], "url": d["url"]}


def create_simple_checkout(cfg: dict, label: str, amount_cents: int,
                           ref: str, return_url: str) -> dict | None:
    """One named amount, one hosted page — for things that aren't orders:
    a project deposit, a final invoice. Returns {id, url} or None when
    Stripe is not configured; the manual confirmation path stays for cheques
    and bank transfers."""
    if not enabled(cfg) or amount_cents <= 0:
        return None
    data = {
        "mode": "payment",
        "success_url": return_url,
        "cancel_url": return_url,
        "client_reference_id": ref,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": label[:120],
    }
    r = httpx.post(f"{API}/checkout/sessions", data=data,
                   auth=(cfg["stripe_secret_key"], ""), timeout=20)
    r.raise_for_status()
    d = r.json()
    return {"id": d["id"], "url": d["url"]}


def refund(cfg: dict, session_id: str, amount_cents: int | None = None) -> bool:
    """Refund a paid Checkout session (full, or partial via amount_cents).
    Returns True when Stripe accepted the refund."""
    if not enabled(cfg) or not session_id:
        return False
    r = httpx.get(f"{API}/checkout/sessions/{session_id}",
                  auth=(cfg["stripe_secret_key"], ""), timeout=20)
    if r.status_code != 200:
        return False
    intent = r.json().get("payment_intent")
    if not intent:
        return False
    data = {"payment_intent": intent}
    if amount_cents:
        data["amount"] = str(amount_cents)
    r2 = httpx.post(f"{API}/refunds", data=data,
                    auth=(cfg["stripe_secret_key"], ""), timeout=20)
    return r2.status_code == 200


def session_paid(cfg: dict, session_id: str) -> bool:
    if not enabled(cfg) or not session_id:
        return False
    r = httpx.get(f"{API}/checkout/sessions/{session_id}",
                  auth=(cfg["stripe_secret_key"], ""), timeout=20)
    if r.status_code != 200:
        return False
    return r.json().get("payment_status") == "paid"


# ---------- recurring: a plan that bills every month ----------
# One-time checkout above sells a thing. This sells a commitment, and the
# difference that matters is not the Stripe mode — it is that a price the
# customer agreed to on a Tuesday has to still be the price in March. The
# amount is sent per subscription rather than pinned to a Stripe Price
# object, so raising the list price never silently raises anybody's bill.

def create_subscription_checkout(cfg: dict, label: str, amount_cents: int,
                                 ref: str, return_url: str,
                                 interval: str = "month",
                                 email: str = "") -> dict | None:
    """Hosted checkout in subscription mode. Returns {id, url}, or None when
    Stripe is not configured — the caller then falls back to invoicing,
    which is a real answer and not an error."""
    if not enabled(cfg) or amount_cents <= 0:
        return None
    if interval not in ("day", "week", "month", "year"):
        raise ValueError(f"unsupported billing interval: {interval}")
    sep = "&" if "?" in return_url else "?"
    data = {
        "mode": "subscription",
        "success_url": f"{return_url}{sep}sid=" "{CHECKOUT_SESSION_ID}",
        "cancel_url": f"{return_url}{sep}cancelled=1",
        "client_reference_id": ref,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][recurring][interval]": interval,
        "line_items[0][price_data][product_data][name]": label[:120],
    }
    if email:
        data["customer_email"] = email[:200]
    r = httpx.post(f"{API}/checkout/sessions", data=data,
                   auth=(cfg["stripe_secret_key"], ""), timeout=20)
    r.raise_for_status()
    d = r.json()
    return {"id": d["id"], "url": d["url"]}


def session_subscription(cfg: dict, session_id: str) -> dict | None:
    """What a returning subscriber's session actually became. Read from
    Stripe rather than trusted from the redirect — the return URL is a thing
    anybody can type."""
    if not enabled(cfg) or not session_id:
        return None
    r = httpx.get(f"{API}/checkout/sessions/{session_id}",
                  auth=(cfg["stripe_secret_key"], ""), timeout=20)
    if r.status_code != 200:
        return None
    d = r.json()
    sub = d.get("subscription")
    if not sub:
        return None
    return {"subscription": sub,
            "paid": d.get("payment_status") in ("paid", "no_payment_required"),
            "customer": d.get("customer") or ""}


def cancel_subscription(cfg: dict, sub_id: str,
                        at_period_end: bool = True) -> bool:
    """Stop the billing. At period end by default: they paid for this month,
    so they keep this month."""
    if not enabled(cfg) or not sub_id:
        return False
    if at_period_end:
        r = httpx.post(f"{API}/subscriptions/{sub_id}",
                       data={"cancel_at_period_end": "true"},
                       auth=(cfg["stripe_secret_key"], ""), timeout=20)
    else:
        r = httpx.delete(f"{API}/subscriptions/{sub_id}",
                         auth=(cfg["stripe_secret_key"], ""), timeout=20)
    return r.status_code == 200


def resume_subscription(cfg: dict, sub_id: str) -> bool:
    """Undo a cancel-at-period-end, while the period is still running."""
    if not enabled(cfg) or not sub_id:
        return False
    r = httpx.post(f"{API}/subscriptions/{sub_id}",
                   data={"cancel_at_period_end": "false"},
                   auth=(cfg["stripe_secret_key"], ""), timeout=20)
    return r.status_code == 200
