"""Optional Stripe Checkout. No secret key configured -> card payments are
off and orders fall back to pay-on-delivery (customers) / on-terms
(distributors). With a key, checkout happens on Stripe's hosted page and we
verify the session server-side on return — no card data ever touches us."""
import httpx

API = "https://api.stripe.com/v1"


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("stripe_secret_key"))


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
