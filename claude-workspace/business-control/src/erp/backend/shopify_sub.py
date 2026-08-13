"""Private Shopify subscription app — the billing trigger for box cycles.

Shopify owns the vault, contracts, SCA, and card charging; this module is the
scheduler that walks active subscription contracts on bill day and fires
`subscriptionBillingAttemptCreate`, idempotently per contract per cycle.

No shop configured -> mock mode: a small fake contract book lets the whole
bill-run pipeline (idempotency, outcome recording, cycle-count sync) run and
be tested without a store. Configure data/config.json `shopify` to go live
against a dev store."""
import json
import secrets

import httpx

from . import db

MOCK_CONTRACTS = [
    {"id": "gid://shopify/SubscriptionContract/9001", "status": "ACTIVE"},
    {"id": "gid://shopify/SubscriptionContract/9002", "status": "ACTIVE"},
    {"id": "gid://shopify/SubscriptionContract/9003", "status": "PAUSED"},
]


def cfg_of(cfg: dict) -> dict:
    return cfg.get("shopify", {})


def enabled(cfg: dict) -> bool:
    s = cfg_of(cfg)
    return bool(s.get("shop_domain") and s.get("admin_token"))


def gql(cfg: dict, query: str, variables: dict | None = None) -> dict:
    s = cfg_of(cfg)
    r = httpx.post(
        f"https://{s['shop_domain']}/admin/api/"
        f"{s.get('api_version', '2026-07')}/graphql.json",
        headers={"X-Shopify-Access-Token": s["admin_token"],
                 "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}}, timeout=20)
    r.raise_for_status()
    out = r.json()
    if out.get("errors"):
        raise RuntimeError(str(out["errors"])[:300])
    return out["data"]


def ping(cfg: dict) -> dict:
    if not enabled(cfg):
        return {"connected": False, "mode": "mock",
                "mock_contracts": len(MOCK_CONTRACTS)}
    d = gql(cfg, "{ shop { name myshopifyDomain currencyCode } }")
    return {"connected": True, "mode": "live", "shop": d["shop"]}


def create_selling_plan(cfg: dict, name: str, interval: str = "MONTH",
                        percent_off: float = 10.0) -> dict:
    """Create a subscribe-&-save selling plan group ready to attach to
    products. In mock mode, returns a fake id so the flow is exercisable."""
    if not enabled(cfg):
        return {"id": f"gid://mock/SellingPlanGroup/{secrets.token_hex(3)}",
                "mode": "mock"}
    q = """
    mutation($input: SellingPlanGroupInput!) {
      sellingPlanGroupCreate(input: $input) {
        sellingPlanGroup { id name }
        userErrors { field message } } }"""
    v = {"input": {
        "name": name, "merchantCode": name.lower().replace(" ", "-"),
        "options": ["Delivery every"],
        "sellingPlansToCreate": [{
            "name": f"Every {interval.lower()}",
            "options": [interval.title()],
            "category": "SUBSCRIPTION",
            "billingPolicy": {"recurring": {"interval": interval,
                                            "intervalCount": 1}},
            "deliveryPolicy": {"recurring": {"interval": interval,
                                             "intervalCount": 1}},
            "pricingPolicies": [{"fixed": {
                "adjustmentType": "PERCENTAGE",
                "adjustmentValue": {"percentage": percent_off}}}],
        }]}}
    d = gql(cfg, q, v)["sellingPlanGroupCreate"]
    if d["userErrors"]:
        raise RuntimeError(str(d["userErrors"]))
    return d["sellingPlanGroup"]


def active_contracts(cfg: dict) -> list[dict]:
    if not enabled(cfg):
        return [c for c in MOCK_CONTRACTS if c["status"] == "ACTIVE"]
    q = """
    { subscriptionContracts(first: 100, query: "status:ACTIVE") {
        nodes { id status nextBillingDate
                customer { id displayName email } } } }"""
    return gql(cfg, q)["subscriptionContracts"]["nodes"]


def bill_run(con, cfg: dict, cycle_month: str) -> dict:
    """Fire a billing attempt for every active contract, exactly once per
    contract per cycle (rerun-safe: already-attempted contracts are skipped).
    Outcomes land in sub_billing; webhooks flip pending -> success/failure."""
    attempted = skipped = 0
    for contract in active_contracts(cfg):
        cur = con.execute(
            "INSERT OR IGNORE INTO sub_billing(contract_id,cycle_month,"
            " status,created_at) VALUES(?,?,?,?)",
            (contract["id"], cycle_month, "pending", db.now()))
        con.commit()
        if not cur.rowcount:
            skipped += 1
            continue
        if enabled(cfg):
            q = """
            mutation($id: ID!, $input: SubscriptionBillingAttemptInput!) {
              subscriptionBillingAttemptCreate(
                subscriptionContractId: $id, subscriptionBillingAttemptInput: $input) {
                subscriptionBillingAttempt { id }
                userErrors { field message } } }"""
            try:
                d = gql(cfg, q, {"id": contract["id"], "input": {
                    "idempotencyKey": f"{cycle_month}:{contract['id']}"}})
                node = d["subscriptionBillingAttemptCreate"]
                status = ("pending" if not node["userErrors"]
                          else f"error: {node['userErrors']}"[:200])
            except Exception as e:
                status = f"error: {e}"[:200]
        else:
            status = "success (mock)"     # mock attempts succeed immediately
        con.execute("UPDATE sub_billing SET status=? WHERE contract_id=? AND"
                    " cycle_month=?", (status, contract["id"], cycle_month))
        con.commit()
        attempted += 1
    billed = con.execute(
        "SELECT COUNT(*) c FROM sub_billing WHERE cycle_month=? AND"
        " status LIKE 'success%'", (cycle_month,)).fetchone()["c"]
    con.execute("UPDATE box_cycles SET billed_count=? WHERE month=?",
                (billed, cycle_month))
    con.commit()
    return {"attempted": attempted, "already_attempted": skipped,
            "billed_success": billed,
            "mode": "live" if enabled(cfg) else "mock"}


def verify_webhook(cfg: dict, raw: bytes, hmac_header: str) -> bool:
    import base64
    import hashlib
    import hmac as hmac_mod
    secret = cfg_of(cfg).get("webhook_secret", "")
    if not secret:
        return False
    digest = hmac_mod.new(secret.encode(), raw, hashlib.sha256).digest()
    return hmac_mod.compare_digest(base64.b64encode(digest).decode(),
                                   hmac_header)


def handle_webhook(con, cfg: dict, topic: str, payload: dict) -> str:
    """Billing outcomes flip sub_billing rows and refresh cycle counts."""
    if topic == "subscription_billing_attempts/success":
        cid = payload.get("subscription_contract_id", "")
        con.execute("UPDATE sub_billing SET status='success' WHERE"
                    " contract_id LIKE ? AND status='pending'", (f"%{cid}",))
    elif topic == "subscription_billing_attempts/failure":
        cid = payload.get("subscription_contract_id", "")
        con.execute("UPDATE sub_billing SET status=? WHERE contract_id LIKE ?"
                    " AND status='pending'",
                    (f"failed: {payload.get('error_code', '?')}"[:100],
                     f"%{cid}"))
    else:
        return "ignored"
    con.commit()
    for row in con.execute("SELECT DISTINCT cycle_month FROM sub_billing"):
        m = row["cycle_month"]
        billed = con.execute(
            "SELECT COUNT(*) c FROM sub_billing WHERE cycle_month=? AND"
            " status LIKE 'success%'", (m,)).fetchone()["c"]
        con.execute("UPDATE box_cycles SET billed_count=? WHERE month=?",
                    (billed, m))
    con.commit()
    return "processed"
