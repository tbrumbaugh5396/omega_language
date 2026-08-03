"""Zero-sum credit ledger. All credit movement goes through post()."""
import secrets
import sqlite3

from .db import now


class LedgerError(Exception):
    pass


def begin_write(con: sqlite3.Connection) -> None:
    """Take the write lock NOW (BEGIN IMMEDIATE), before any balance reads.

    Python's sqlite3 runs SELECTs in autocommit and only starts the write
    transaction at the first INSERT/UPDATE — so without this, two concurrent
    requests can both pass a balance check and overdraw the account. Callers
    hold the lock until their `with con:` block commits. No-op if this
    connection already holds a transaction (and therefore the lock).
    """
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")


def balance(con: sqlite3.Connection, account: str) -> int:
    row = con.execute(
        "SELECT COALESCE(SUM(delta),0) AS b FROM ledger WHERE account=?", (account,)
    ).fetchone()
    return row["b"]


def post(con: sqlite3.Connection, entries: list, kind: str, ref: str = None,
         memo: str = None, allow_negative: tuple = ("house",)) -> str:
    """entries: [(account, delta), ...] — must sum to zero.

    User and market accounts may not go negative; 'house' may (it is the
    operator's subsidy/at-risk account, e.g. fixed-odds books and LMSR).
    Caller is responsible for wrapping in a transaction (with con:).
    """
    if sum(d for _, d in entries) != 0:
        raise LedgerError("ledger entries must sum to zero")
    begin_write(con)  # overdraft checks below must happen under the write lock
    txn = secrets.token_hex(8)
    ts = now()
    for account, delta in entries:
        if delta == 0:
            continue
        if delta < 0 and account not in allow_negative:
            if balance(con, account) + delta < 0:
                raise LedgerError(f"insufficient balance in {account}")
        con.execute(
            "INSERT INTO ledger(txn,account,delta,kind,ref,memo,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (txn, account, delta, kind, ref, memo, ts),
        )
    return txn


def user_account(user_id: int) -> str:
    return f"user:{user_id}"


def market_account(market_id: int) -> str:
    return f"market:{market_id}"
