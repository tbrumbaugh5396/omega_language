"""Market mechanisms: parimutuel pools, fixed odds, LMSR market maker.

All stakes flow user -> market:<id> escrow at bet time. Settlement moves
escrow to winners (and rake/surplus to house; house covers any shortfall on
fixed-odds and LMSR books — that is the operator's advertised risk).
"""
import math
import sqlite3

from . import ledger
from .db import now


class BetError(Exception):
    pass


def lmsr_cost(qs: list, b: float) -> float:
    m = max(q / b for q in qs)
    return b * (m + math.log(sum(math.exp(q / b - m) for q in qs)))


def lmsr_prices(qs: list, b: float) -> list:
    m = max(q / b for q in qs)
    exps = [math.exp(q / b - m) for q in qs]
    s = sum(exps)
    return [e / s for e in exps]


def lmsr_shares_for_stake(qs: list, i: int, stake: float, b: float) -> float:
    """Closed form: shares bought on outcome i for `stake` credits."""
    m = max(q / b for q in qs)
    total = sum(math.exp(q / b - m) for q in qs)
    others = total - math.exp(qs[i] / b - m)
    # e^{(q_i+d)/b - m} = (total) * e^{stake/(b)} ... derived from C(q+d)-C(q)=stake
    target = total * math.exp(stake / b) - others
    if target <= 0:
        raise BetError("stake too small to price")
    return b * (math.log(target) + m) - qs[i]


def quote(market: sqlite3.Row, outcomes: list, outcome_id: int, stake: int) -> dict:
    """What would this stake return if it wins? (informational, pre-bet)"""
    mech = market["mechanism"]
    out = {o["id"]: o for o in outcomes}
    if outcome_id not in out:
        raise BetError("unknown outcome")
    if mech == "fixed":
        odds = out[outcome_id]["fixed_odds"] or 1.0
        return {"kind": "fixed", "odds": odds, "payout_if_win": int(stake * odds)}
    if mech == "parimutuel":
        total = sum(o["pool"] for o in outcomes) + stake
        pool = out[outcome_id]["pool"] + stake
        rake = total * market["rake_bps"] // 10000
        est = int(stake / pool * (total - rake)) if pool else 0
        return {"kind": "parimutuel", "implied_odds": round(total / pool, 3) if pool else None,
                "payout_if_win_now": est}
    if mech == "lmsr":
        qs = [o["shares"] for o in outcomes]
        idx = [o["id"] for o in outcomes].index(outcome_id)
        shares = lmsr_shares_for_stake(qs, idx, float(stake), market["lmsr_b"])
        return {"kind": "lmsr", "shares": round(shares, 4),
                "payout_if_win": int(shares),
                "price": round(lmsr_prices(qs, market["lmsr_b"])[idx], 4)}
    raise BetError(f"unknown mechanism {mech}")


def place_bet(con: sqlite3.Connection, market: sqlite3.Row, outcomes: list,
              user_id: int, outcome_id: int, stake: int) -> dict:
    if stake <= 0:
        raise BetError("stake must be positive")
    if outcome_id not in {o["id"] for o in outcomes}:
        raise BetError("unknown outcome")

    mech = market["mechanism"]
    with con:
        # Everything below happens under the write lock: re-read market state
        # (a concurrent settle/close must not race us) and price from fresh
        # outcome rows (concurrent LMSR bets must move the price sequentially).
        ledger.begin_write(con)
        m = con.execute("SELECT status, close_at FROM markets WHERE id=?",
                        (market["id"],)).fetchone()
        if m["status"] != "open":
            raise BetError("market is not open")
        if m["close_at"] and now() >= m["close_at"]:
            raise BetError("market has closed")
        outs = con.execute("SELECT * FROM outcomes WHERE market_id=? ORDER BY id",
                           (market["id"],)).fetchall()
        out = {o["id"]: o for o in outs}

        odds_at_bet = None
        shares = None
        if mech == "fixed":
            odds_at_bet = out[outcome_id]["fixed_odds"]
            if not odds_at_bet or odds_at_bet <= 1.0:
                raise BetError("this outcome has no odds set")
        elif mech == "lmsr":
            qs = [o["shares"] for o in outs]
            idx = [o["id"] for o in outs].index(outcome_id)
            shares = lmsr_shares_for_stake(qs, idx, float(stake), market["lmsr_b"])

        ledger.post(
            con,
            [(ledger.user_account(user_id), -stake),
             (ledger.market_account(market["id"]), stake)],
            kind="bet", ref=f"market:{market['id']}",
        )
        cur = con.execute(
            "INSERT INTO bets(market_id,outcome_id,user_id,stake,odds_at_bet,shares,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (market["id"], outcome_id, user_id, stake, odds_at_bet, shares, now()),
        )
        con.execute("UPDATE outcomes SET pool=pool+? WHERE id=?", (stake, outcome_id))
        if shares is not None:
            con.execute("UPDATE outcomes SET shares=shares+? WHERE id=?", (shares, outcome_id))
    return {"bet_id": cur.lastrowid, "odds_at_bet": odds_at_bet, "shares": shares}


def settle(con: sqlite3.Connection, market: sqlite3.Row, winner_outcome_id: int) -> dict:
    """Resolve a market: pay winners from escrow (house covers shortfalls)."""
    mid = market["id"]
    escrow = ledger.market_account(mid)
    mech = market["mechanism"]

    with con:
        # Lock first: bets, escrow and status must be read under the write
        # lock or a concurrent bet/second resolve could slip between them.
        ledger.begin_write(con)
        status = con.execute("SELECT status FROM markets WHERE id=?",
                             (mid,)).fetchone()["status"]
        if status in ("resolved", "void"):
            raise BetError(f"market is already {status}")
        bets = con.execute("SELECT * FROM bets WHERE market_id=? AND settled=0",
                           (mid,)).fetchall()
        payouts = _compute_payouts(market, bets, winner_outcome_id)
        pot = ledger.balance(con, escrow)
        total_out = sum(payouts.values())
        # Sweep escrow to house, then pay winners from house. Net house effect:
        # pot - total_out (positive = rake/surplus, negative = book loss).
        entries = [(escrow, -pot), ("house", pot)]
        for b in bets:
            p = payouts.get(b["id"], 0)
            con.execute("UPDATE bets SET settled=1, payout=? WHERE id=?", (p, b["id"]))
            if p > 0:
                entries.append(("house", -p))
                entries.append((ledger.user_account(b["user_id"]), p))
        ledger.post(con, entries, kind="payout", ref=f"market:{mid}")
        con.execute(
            "UPDATE markets SET status='resolved', winner_outcome_id=? WHERE id=?",
            (winner_outcome_id, mid),
        )
    return {"bets_settled": len(bets), "total_paid": total_out, "house_net": pot - total_out}


def _compute_payouts(market: sqlite3.Row, bets: list, winner_outcome_id: int) -> dict:
    """bet_id -> credits for the winning outcome, per mechanism. Pure."""
    mech = market["mechanism"]
    payouts = {}

    if mech == "parimutuel":
        total = sum(b["stake"] for b in bets)
        rake = total * market["rake_bps"] // 10000
        winners = [b for b in bets if b["outcome_id"] == winner_outcome_id]
        wtotal = sum(b["stake"] for b in winners)
        if wtotal == 0:
            # nobody picked the winner: refund everyone, no rake
            payouts = {b["id"]: b["stake"] for b in bets}
        else:
            distributable = total - rake
            for b in winners:
                payouts[b["id"]] = b["stake"] * distributable // wtotal
    elif mech == "fixed":
        for b in bets:
            if b["outcome_id"] == winner_outcome_id:
                payouts[b["id"]] = int(b["stake"] * b["odds_at_bet"])
    elif mech == "lmsr":
        for b in bets:
            if b["outcome_id"] == winner_outcome_id:
                payouts[b["id"]] = int(b["shares"])  # 1 credit per share
    else:
        raise BetError(f"unknown mechanism {mech}")
    return payouts


def void(con: sqlite3.Connection, market: sqlite3.Row) -> int:
    """Cancel a market and refund all stakes."""
    mid = market["id"]
    with con:
        ledger.begin_write(con)  # a concurrent bet must not miss the refund
        status = con.execute("SELECT status FROM markets WHERE id=?",
                             (mid,)).fetchone()["status"]
        if status in ("resolved", "void"):
            raise BetError(f"market is already {status}")
        bets = con.execute("SELECT * FROM bets WHERE market_id=? AND settled=0",
                           (mid,)).fetchall()
        entries = []
        for b in bets:
            entries.append((ledger.market_account(mid), -b["stake"]))
            entries.append((ledger.user_account(b["user_id"]), b["stake"]))
            con.execute("UPDATE bets SET settled=1, payout=stake WHERE id=?", (b["id"],))
        if entries:
            ledger.post(con, entries, kind="refund", ref=f"market:{mid}")
        con.execute("UPDATE markets SET status='void' WHERE id=?", (mid,))
    return len(bets)
