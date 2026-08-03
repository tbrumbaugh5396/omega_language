"""Every Reward — FastAPI backend. Serves the API and the PWA frontend."""
import json
import shutil
import sqlite3
import threading
import time

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, catalog, chain, config, db, engines, ledger, monero, resolvers

app = FastAPI(title="Every Reward")
CFG = config.load()
db.init()


# ---------- helpers ----------

def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def current_user(authorization: str = Header(default=""), con=Depends(get_con)):
    token = authorization.removeprefix("Bearer ").strip()
    user = auth.user_for_token(con, token)
    if user is None:
        raise HTTPException(401, "not signed in")
    return user


def admin_user(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "admin only")
    return user


def market_json(con, m) -> dict:
    outs = con.execute(
        "SELECT * FROM outcomes WHERE market_id=? ORDER BY id", (m["id"],)
    ).fetchall()
    d = dict(m)
    d["outcomes"] = [dict(o) for o in outs]
    total = sum(o["pool"] for o in outs)
    d["total_staked"] = total
    if m["mechanism"] == "lmsr" and outs:
        prices = engines.lmsr_prices([o["shares"] for o in outs], m["lmsr_b"])
        for o, p in zip(d["outcomes"], prices):
            o["price"] = round(p, 4)
    elif m["mechanism"] == "parimutuel" and total:
        for o in d["outcomes"]:
            o["implied_odds"] = round(total / o["pool"], 3) if o["pool"] else None
    return d


# ---------- auth ----------

class VerifyBody(BaseModel):
    address: str
    signature: str


class DevLoginBody(BaseModel):
    nickname: str
    admin_key: str = ""


@app.get("/api/info")
def info():
    return {
        "app": "Every Reward",
        "chain_id": CFG["chain_id"],
        "chain_name": CFG["chain_name"],
        "deposit_address": CFG["deposit_address"],
        "credits_per_eth": CFG["credits_per_eth"],
        "tokens": CFG.get("tokens", {}),
        "min_confirmations": CFG["min_confirmations"],
        "dev_login": CFG["dev_login"],
        "deposits_enabled": bool(CFG["deposit_address"]),
        "monero": {
            "enabled": monero.enabled(CFG),
            "address": CFG["monero"].get("address", ""),
            "credits_per_xmr": CFG["monero"].get("credits_per_xmr", 0),
            "min_confirmations": CFG["monero"].get("min_confirmations", 10),
        },
    }


@app.get("/api/auth/nonce")
def get_nonce(address: str, con=Depends(get_con)):
    nonce = auth.issue_nonce(con, address)
    return {"nonce": nonce, "message": auth.login_message(address, nonce)}


@app.post("/api/auth/verify")
def verify(body: VerifyBody, con=Depends(get_con)):
    row = con.execute(
        "SELECT nonce FROM nonces WHERE address=?", (body.address.lower(),)
    ).fetchone()
    if row is None:
        raise HTTPException(400, "request a nonce first")
    if not auth.verify_signature(body.address, row["nonce"], body.signature):
        raise HTTPException(401, "signature did not verify")
    with con:
        con.execute("DELETE FROM nonces WHERE address=?", (body.address.lower(),))
    user = auth.get_or_create_user(con, body.address, CFG)
    token = auth.create_session(con, user["id"])
    return {"token": token, "user": dict(user)}


@app.post("/api/auth/dev")
def dev_login(body: DevLoginBody, con=Depends(get_con)):
    if not CFG["dev_login"]:
        raise HTTPException(403, "dev login is disabled")
    user = auth.create_dev_user(con, body.nickname, body.admin_key, CFG)
    token = auth.create_session(con, user["id"])
    return {"token": token, "user": dict(user)}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default=""), user=Depends(current_user),
           con=Depends(get_con)):
    token = authorization.removeprefix("Bearer ").strip()
    with con:
        con.execute("DELETE FROM sessions WHERE token=?", (token,))
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user), con=Depends(get_con)):
    return {"user": dict(user),
            "balance": ledger.balance(con, ledger.user_account(user["id"]))}


# ---------- wallet ----------

class DepositBody(BaseModel):
    tx_hash: str
    tx_key: str = ""  # present => Monero claim (txid + per-tx secret key)


@app.get("/api/wallet")
def wallet(user=Depends(current_user), con=Depends(get_con)):
    acct = ledger.user_account(user["id"])
    history = con.execute(
        "SELECT delta, kind, ref, memo, created_at FROM ledger "
        "WHERE account=? ORDER BY id DESC LIMIT 100", (acct,)
    ).fetchall()
    deposits = con.execute(
        "SELECT tx_hash, amount_wei, credits, status, detail, created_at "
        "FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 50", (user["id"],)
    ).fetchall()
    return {"balance": ledger.balance(con, acct),
            "history": [dict(r) for r in history],
            "deposits": [dict(r) for r in deposits]}


@app.post("/api/deposit")
def deposit(body: DepositBody, user=Depends(current_user), con=Depends(get_con)):
    tx_hash = body.tx_hash.strip().lower()
    dup = con.execute("SELECT id FROM deposits WHERE tx_hash=?", (tx_hash,)).fetchone()
    if dup:
        raise HTTPException(400, "that transaction was already claimed")
    try:
        if body.tx_key:
            # Monero: possession of the tx_key proves the claimant is the
            # sender, so no address binding is possible or needed.
            result = monero.verify_deposit(CFG, tx_hash, body.tx_key)
        else:
            # EVM: wallet-authenticated users may only claim their own txs.
            result = chain.verify_deposit(CFG, tx_hash, expected_from=user["address"])
    except (chain.ChainError, monero.MoneroError) as e:
        raise HTTPException(400, str(e))
    credits = result["credits"]
    if credits <= 0:
        raise HTTPException(400, "deposit too small to yield any credits")
    try:
        with con:
            con.execute(
                "INSERT INTO deposits(user_id,tx_hash,asset,amount_wei,credits,"
                "status,detail,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (user["id"], tx_hash, result["asset"], str(result["amount_raw"]),
                 credits, "confirmed",
                 f"from {result['from']}" if result["from"] else "sender anonymous (XMR)",
                 db.now()),
            )
            ledger.post(
                con,
                [("house", -credits), (ledger.user_account(user["id"]), credits)],
                kind="deposit", ref=f"tx:{tx_hash}", memo=result["asset"],
            )
    except sqlite3.IntegrityError:
        # concurrent claim of the same tx: UNIQUE(tx_hash) is the backstop
        raise HTTPException(400, "that transaction was already claimed")
    return {"credits": credits, "asset": result["asset"],
            "balance": ledger.balance(con, ledger.user_account(user["id"]))}


# ---------- pack openings ----------
# Integrity rule enforced here, not by trust: the video slot only unlocks once
# every linked market is closed, so the opener can never take bets on a pull
# they have already seen.

VIDEO_DIR = config.DATA_DIR / "videos"


class OpeningIn(BaseModel):
    title: str
    description: str = ""
    game: str = "pokemon"


def opening_json(con, o) -> dict:
    d = dict(o)
    d.pop("video_path", None)  # server-side detail
    d["has_video"] = o["status"] == "revealed" and bool(o["video_path"])
    markets = con.execute(
        "SELECT * FROM markets WHERE opening_id=? ORDER BY id", (o["id"],)).fetchall()
    d["markets"] = [market_json(con, m) for m in markets]
    return d


@app.get("/api/openings")
def list_openings(con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM openings ORDER BY (status!='revealed') DESC, id DESC").fetchall()
    return {"openings": [opening_json(con, o) for o in rows]}


@app.post("/api/openings")
def create_opening(body: OpeningIn, user=Depends(admin_user), con=Depends(get_con)):
    with con:
        cur = con.execute(
            "INSERT INTO openings(title,description,game,creator_id,created_at) "
            "VALUES(?,?,?,?,?)",
            (body.title, body.description, body.game, user["id"], db.now()))
    o = con.execute("SELECT * FROM openings WHERE id=?", (cur.lastrowid,)).fetchone()
    return opening_json(con, o)


@app.post("/api/openings/{opening_id}/seal")
def seal_opening(opening_id: int, user=Depends(admin_user), con=Depends(get_con)):
    o = con.execute("SELECT * FROM openings WHERE id=?", (opening_id,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such opening")
    if o["status"] != "open":
        raise HTTPException(400, f"opening is already {o['status']}")
    with con:
        con.execute(
            "UPDATE markets SET status='closed' WHERE opening_id=? AND status='open'",
            (opening_id,))
        con.execute("UPDATE openings SET status='sealed' WHERE id=?", (opening_id,))
    return {"ok": True}


@app.post("/api/openings/{opening_id}/video")
def upload_video(opening_id: int, file: UploadFile,
                 user=Depends(admin_user), con=Depends(get_con)):
    o = con.execute("SELECT * FROM openings WHERE id=?", (opening_id,)).fetchone()
    if o is None:
        raise HTTPException(404, "no such opening")
    if o["status"] == "open":
        raise HTTPException(400, "seal betting before uploading the reveal — "
                                 "bets must close before the result can exist")
    still_open = con.execute(
        "SELECT COUNT(*) c FROM markets WHERE opening_id=? AND status='open'",
        (opening_id,)).fetchone()["c"]
    if still_open:
        raise HTTPException(400, "some linked markets are still open")
    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(400, "upload a video file (webm/mp4)")
    ext = ".mp4" if "mp4" in (file.content_type or "") else ".webm"
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    dest = VIDEO_DIR / f"opening_{opening_id}{ext}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    with con:
        con.execute(
            "UPDATE openings SET status='revealed', video_path=?, "
            "video_uploaded_at=? WHERE id=?",
            (dest.name, db.now(), opening_id))
    return {"ok": True, "bytes": dest.stat().st_size}


@app.get("/api/openings/{opening_id}/video")
def get_video(opening_id: int, con=Depends(get_con)):
    o = con.execute("SELECT * FROM openings WHERE id=?", (opening_id,)).fetchone()
    if o is None or not o["video_path"]:
        raise HTTPException(404, "no video")
    if o["status"] != "revealed":
        raise HTTPException(403, "video is sealed until betting closes")
    path = VIDEO_DIR / o["video_path"]
    if not path.exists():
        raise HTTPException(404, "video file missing")
    media = "video/mp4" if path.suffix == ".mp4" else "video/webm"
    return FileResponse(path, media_type=media)


# ---------- markets ----------

class OutcomeIn(BaseModel):
    label: str
    fixed_odds: float | None = None


class MarketIn(BaseModel):
    title: str
    description: str = ""
    mechanism: str  # parimutuel | fixed | lmsr
    outcomes: list[OutcomeIn]
    close_at: int | None = None
    resolver: str = "manual"
    resolver_config: dict = {}
    rake_bps: int | None = None
    lmsr_b: float | None = None
    opening_id: int | None = None


class BetIn(BaseModel):
    outcome_id: int
    stake: int


class ResolveIn(BaseModel):
    winner_outcome_id: int | None = None


@app.get("/api/markets")
def list_markets(con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM markets ORDER BY (status='open') DESC, id DESC"
    ).fetchall()
    return {"markets": [market_json(con, m) for m in rows]}


@app.get("/api/markets/{market_id}")
def get_market(market_id: int, con=Depends(get_con)):
    m = con.execute("SELECT * FROM markets WHERE id=?", (market_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such market")
    return market_json(con, m)


@app.post("/api/markets")
def create_market(body: MarketIn, user=Depends(admin_user), con=Depends(get_con)):
    if body.mechanism not in ("parimutuel", "fixed", "lmsr"):
        raise HTTPException(400, "mechanism must be parimutuel, fixed or lmsr")
    if len(body.outcomes) < 2:
        raise HTTPException(400, "need at least two outcomes")
    if body.mechanism == "fixed":
        for o in body.outcomes:
            if not o.fixed_odds or o.fixed_odds <= 1.0:
                raise HTTPException(400, f"outcome {o.label!r} needs decimal odds > 1.0")
    if body.opening_id is not None:
        op = con.execute("SELECT status FROM openings WHERE id=?",
                         (body.opening_id,)).fetchone()
        if op is None:
            raise HTTPException(400, "no such opening")
        if op["status"] != "open":
            raise HTTPException(400, "that opening is sealed — betting is over")
    with con:
        cur = con.execute(
            "INSERT INTO markets(title,description,mechanism,close_at,resolver,"
            "resolver_config,rake_bps,lmsr_b,opening_id,creator_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (body.title, body.description, body.mechanism, body.close_at,
             body.resolver, json.dumps(body.resolver_config),
             body.rake_bps if body.rake_bps is not None else CFG["default_rake_bps"],
             body.lmsr_b if body.lmsr_b is not None else CFG["default_lmsr_b"],
             body.opening_id, user["id"], db.now()),
        )
        mid = cur.lastrowid
        for o in body.outcomes:
            con.execute(
                "INSERT INTO outcomes(market_id,label,fixed_odds) VALUES(?,?,?)",
                (mid, o.label, o.fixed_odds),
            )
    m = con.execute("SELECT * FROM markets WHERE id=?", (mid,)).fetchone()
    return market_json(con, m)


@app.get("/api/markets/{market_id}/quote")
def quote(market_id: int, outcome_id: int, stake: int, con=Depends(get_con)):
    m = con.execute("SELECT * FROM markets WHERE id=?", (market_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such market")
    outs = con.execute(
        "SELECT * FROM outcomes WHERE market_id=? ORDER BY id", (market_id,)
    ).fetchall()
    try:
        return engines.quote(m, outs, outcome_id, stake)
    except engines.BetError as e:
        raise HTTPException(400, str(e))


@app.post("/api/markets/{market_id}/bet")
def bet(market_id: int, body: BetIn, user=Depends(current_user), con=Depends(get_con)):
    m = con.execute("SELECT * FROM markets WHERE id=?", (market_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such market")
    outs = con.execute(
        "SELECT * FROM outcomes WHERE market_id=? ORDER BY id", (market_id,)
    ).fetchall()
    try:
        result = engines.place_bet(con, m, outs, user["id"], body.outcome_id, body.stake)
    except (engines.BetError, ledger.LedgerError) as e:
        raise HTTPException(400, str(e))
    result["balance"] = ledger.balance(con, ledger.user_account(user["id"]))
    return result


@app.get("/api/bets")
def my_bets(user=Depends(current_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT b.*, m.title, m.status AS market_status, o.label AS outcome_label, "
        "m.winner_outcome_id FROM bets b "
        "JOIN markets m ON m.id=b.market_id JOIN outcomes o ON o.id=b.outcome_id "
        "WHERE b.user_id=? ORDER BY b.id DESC LIMIT 200", (user["id"],)
    ).fetchall()
    return {"bets": [dict(r) for r in rows]}


@app.post("/api/markets/{market_id}/close")
def close_market(market_id: int, user=Depends(admin_user), con=Depends(get_con)):
    with con:
        con.execute(
            "UPDATE markets SET status='closed' WHERE id=? AND status='open'", (market_id,)
        )
    return {"ok": True}


@app.post("/api/markets/{market_id}/resolve")
def resolve_market(market_id: int, body: ResolveIn,
                   user=Depends(admin_user), con=Depends(get_con)):
    m = con.execute("SELECT * FROM markets WHERE id=?", (market_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such market")
    if m["status"] == "resolved":
        raise HTTPException(400, "already resolved")
    outs = con.execute(
        "SELECT * FROM outcomes WHERE market_id=? ORDER BY id", (market_id,)
    ).fetchall()
    winner = body.winner_outcome_id
    evidence = "resolved manually by admin"
    if winner is None:
        try:
            r = resolvers.resolve(CFG, m, outs)
        except (resolvers.ResolveError, chain.ChainError, Exception) as e:
            raise HTTPException(400, f"auto-resolve failed: {e}")
        if r is None:
            raise HTTPException(400, "manual market: pass winner_outcome_id")
        winner, evidence = r["winner_outcome_id"], r["evidence"]
    if winner not in [o["id"] for o in outs]:
        raise HTTPException(400, "winner is not an outcome of this market")
    try:
        result = engines.settle(con, m, winner)
    except engines.BetError as e:
        raise HTTPException(400, str(e))
    result["evidence"] = evidence
    return result


@app.post("/api/markets/{market_id}/void")
def void_market(market_id: int, user=Depends(admin_user), con=Depends(get_con)):
    m = con.execute("SELECT * FROM markets WHERE id=?", (market_id,)).fetchone()
    if m is None:
        raise HTTPException(404, "no such market")
    if m["status"] in ("resolved", "void"):
        raise HTTPException(400, f"market is {m['status']}")
    try:
        refunded = engines.void(con, m)
    except engines.BetError as e:
        raise HTTPException(400, str(e))
    return {"refunded_bets": refunded}


# ---------- store ----------

class ItemIn(BaseModel):
    name: str
    description: str = ""
    price: int
    stock: int = -1
    emoji: str = "🎁"
    active: bool = True


@app.get("/api/store")
def store(con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM store_items WHERE active=1 ORDER BY price"
    ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.post("/api/store/{item_id}/redeem")
def redeem(item_id: int, user=Depends(current_user), con=Depends(get_con)):
    item = con.execute(
        "SELECT * FROM store_items WHERE id=? AND active=1", (item_id,)
    ).fetchone()
    if item is None:
        raise HTTPException(404, "no such item")
    if item["stock"] == 0:
        raise HTTPException(400, "out of stock")
    if item["source"] != "manual":
        age = db.now() - (item["last_synced"] or 0)
        if age > int(CFG.get("catalog_max_age_sec", 900)):
            raise HTTPException(
                400, "price data for this item is stale — try again in a minute")
    try:
        with con:
            ledger.post(
                con,
                [(ledger.user_account(user["id"]), -item["price"]), ("house", item["price"])],
                kind="redeem", ref=f"item:{item_id}", memo=item["name"],
            )
            if item["stock"] > 0:
                # guard in the UPDATE: a concurrent redeem of the last unit
                # must fail here (and roll the ledger entry back), not go to -1
                cur = con.execute(
                    "UPDATE store_items SET stock=stock-1 WHERE id=? AND stock>0",
                    (item_id,)
                )
                if cur.rowcount == 0:
                    raise HTTPException(400, "out of stock")
            con.execute(
                "INSERT INTO redemptions(item_id,user_id,price_paid,created_at) "
                "VALUES(?,?,?,?)", (item_id, user["id"], item["price"], db.now()),
            )
    except ledger.LedgerError as e:
        raise HTTPException(400, str(e))
    return {"ok": True,
            "balance": ledger.balance(con, ledger.user_account(user["id"]))}


@app.get("/api/redemptions")
def my_redemptions(user=Depends(current_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT r.*, i.name, i.emoji FROM redemptions r "
        "JOIN store_items i ON i.id=r.item_id "
        "WHERE r.user_id=? ORDER BY r.id DESC", (user["id"],)
    ).fetchall()
    return {"redemptions": [dict(r) for r in rows]}


# ---------- admin ----------

class GrantIn(BaseModel):
    user_id: int
    amount: int
    memo: str = "admin grant"


@app.post("/api/admin/items")
def create_item(body: ItemIn, user=Depends(admin_user), con=Depends(get_con)):
    with con:
        cur = con.execute(
            "INSERT INTO store_items(name,description,price,stock,emoji,active) "
            "VALUES(?,?,?,?,?,?)",
            (body.name, body.description, body.price, body.stock, body.emoji,
             int(body.active)),
        )
    return {"id": cur.lastrowid}


@app.post("/api/admin/redemptions/{rid}/fulfill")
def fulfill(rid: int, user=Depends(admin_user), con=Depends(get_con)):
    with con:
        con.execute(
            "UPDATE redemptions SET status='fulfilled' WHERE id=? AND status='pending'",
            (rid,),
        )
    return {"ok": True}


@app.post("/api/admin/grant")
def grant(body: GrantIn, user=Depends(admin_user), con=Depends(get_con)):
    with con:
        ledger.post(
            con,
            [("house", -body.amount), (ledger.user_account(body.user_id), body.amount)],
            kind="grant", memo=body.memo,
        )
    return {"balance": ledger.balance(con, ledger.user_account(body.user_id))}


class CatalogIn(BaseModel):
    source: str
    source_id: str
    markup_bps: int | None = None
    stock: int = -1


def _catalog_quote(body: CatalogIn):
    markup = body.markup_bps if body.markup_bps is not None else CFG["default_markup_bps"]
    try:
        info = catalog.fetch(CFG, body.source, body.source_id)
    except catalog.CatalogError as e:
        raise HTTPException(400, str(e))
    info["markup_bps"] = markup
    info["credits"] = catalog.price_credits(CFG, info["price_cents"], markup)
    return info


@app.post("/api/admin/catalog/preview")
def catalog_preview(body: CatalogIn, user=Depends(admin_user)):
    return _catalog_quote(body)


@app.post("/api/admin/catalog/add")
def catalog_add(body: CatalogIn, user=Depends(admin_user), con=Depends(get_con)):
    info = _catalog_quote(body)
    dup = con.execute(
        "SELECT id FROM store_items WHERE source=? AND source_id=?",
        (body.source, body.source_id)).fetchone()
    if dup:
        raise HTTPException(400, f"already in the store (item {dup['id']})")
    with con:
        cur = con.execute(
            "INSERT INTO store_items(name,description,price,stock,emoji,active,"
            "source,source_id,base_price_cents,markup_bps,last_synced,image_url) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (info["name"], info["description"], info["credits"], body.stock,
             info["emoji"], int(info["in_stock"]), body.source, body.source_id,
             info["price_cents"], info["markup_bps"], db.now(),
             info.get("image_url")))
    return {"id": cur.lastrowid, **info}


@app.post("/api/admin/catalog/sync")
def catalog_sync(user=Depends(admin_user), con=Depends(get_con)):
    items = con.execute("SELECT * FROM store_items WHERE source!='manual'").fetchall()
    with con:
        results = [{"id": it["id"], "action": catalog.sync_item(con, CFG, it)}
                   for it in items]
    return {"synced": results}


@app.post("/api/admin/items/{item_id}/activate")
def reactivate_item(item_id: int, user=Depends(admin_user), con=Depends(get_con)):
    item = con.execute("SELECT * FROM store_items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(404, "no such item")
    with con:
        if item["source"] != "manual":
            # accept the source's current price as the new baseline
            con.execute("UPDATE store_items SET suspend_reason=NULL, "
                        "base_price_cents=NULL WHERE id=?", (item_id,))
            item = con.execute("SELECT * FROM store_items WHERE id=?",
                               (item_id,)).fetchone()
            action = catalog.sync_item(con, CFG, item)
        else:
            con.execute("UPDATE store_items SET active=1 WHERE id=?", (item_id,))
            action = "activated"
    return {"action": action}


@app.get("/api/admin/overview")
def overview(user=Depends(admin_user), con=Depends(get_con)):
    users = con.execute("SELECT * FROM users ORDER BY id").fetchall()
    out = []
    for u in users:
        d = dict(u)
        d["balance"] = ledger.balance(con, ledger.user_account(u["id"]))
        out.append(d)
    pending = con.execute(
        "SELECT r.*, i.name, i.emoji, u.nickname FROM redemptions r "
        "JOIN store_items i ON i.id=r.item_id JOIN users u ON u.id=r.user_id "
        "WHERE r.status='pending' ORDER BY r.id"
    ).fetchall()
    catalog_items = con.execute(
        "SELECT * FROM store_items WHERE source!='manual' ORDER BY id").fetchall()
    return {"users": out,
            "house_balance": ledger.balance(con, "house"),
            "pending_redemptions": [dict(r) for r in pending],
            "catalog_items": [dict(r) for r in catalog_items],
            "admin_key_hint": CFG["admin_key"][:4] + "…"}


# ---------- background: auto-close and auto-resolve ----------

def _housekeeping_loop():
    while True:
        try:
            con = db.connect()
            with con:
                con.execute(
                    "UPDATE markets SET status='closed' "
                    "WHERE status='open' AND close_at IS NOT NULL AND close_at<=?",
                    (db.now(),),
                )
                con.execute("DELETE FROM sessions WHERE expires_at<=?", (db.now(),))
                catalog.sync_due(con, CFG)
            due = con.execute(
                "SELECT * FROM markets WHERE status='closed' AND resolver!='manual'"
            ).fetchall()
            for m in due:
                outs = con.execute(
                    "SELECT * FROM outcomes WHERE market_id=? ORDER BY id", (m["id"],)
                ).fetchall()
                try:
                    r = resolvers.resolve(CFG, m, outs)
                    if r:
                        engines.settle(con, m, r["winner_outcome_id"])
                except Exception:
                    pass  # retried on the next tick; admin can always resolve manually
            con.close()
        except Exception:
            pass
        time.sleep(60)


threading.Thread(target=_housekeeping_loop, daemon=True).start()


# ---------- static frontend (mounted last so /api wins) ----------

@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR), name="frontend")
