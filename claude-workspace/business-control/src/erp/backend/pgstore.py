"""Rows in Postgres, behind the sqlite3 face the app already wears.

The app talks to its database the sqlite3 way: `con.execute(sql, params)`
with `?` placeholders, rows you index by name, `cur.lastrowid`,
`con.executescript(ddl)`, `PRAGMA table_info`, `INSERT OR IGNORE`, and
errors that are `sqlite3.Error`s. Eighteen hundred call sites do. A
tenant that lives in Postgres cannot be a rewrite of those; it has to be
a connection object that answers the same calls.

That is what this is. `connect(dsn, tenant)` returns something with the
sqlite3.Connection surface the app uses, backed by psycopg, translating
on the way:

  * `?` → `%s`, outside string literals; a literal `%` is escaped.
  * `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`; `INSERT OR REPLACE` →
    `ON CONFLICT (key) DO UPDATE`, the key read from the table's own
    constraints.
  * SQLite's lax `LIKE` (case-insensitive) → `ILIKE`; `COLLATE NOCASE`
    → `lower(...)`.
  * DDL types: `INTEGER PRIMARY KEY` → `BIGSERIAL`, `INTEGER` → `BIGINT`,
    `REAL` → `DOUBLE PRECISION`, `BLOB` → `BYTEA`.
  * `PRAGMA table_info(t)` → the information schema; other PRAGMAs are
    nothing.
  * `lastrowid` → `RETURNING id` on inserts into tables that have one; an
    insert that names its own id moves the sequence past it.
  * Every statement runs in its own savepoint, because SQLite fails a
    statement and carries on while Postgres poisons the transaction —
    and the app's migration loop (`ALTER TABLE ADD COLUMN`, pass on
    error) depends on carrying on.
  * Postgres errors are raised as subclasses of `sqlite3.Error`, so every
    `except sqlite3.Error` fallback in the app (FTS, migrations, probes)
    keeps its meaning.
  * Numbers come back as numbers: a `SUM()` is not a Decimal here.

What it does not do: full-text search (`CREATE VIRTUAL TABLE` raises,
and the product search falls back to ILIKE as it already does without
FTS5), triggers, and the SQLite backup API — a tenant in Postgres is
backed up with pg_dump, and shipped between nodes by not shipping it:
the rows are already reachable from every node.

A few SQLite functions the app's SQL uses are defined in each tenant
database on first connect (`round(double, int)`, `strftime`, `datetime`,
`iif`, `instr`), so the SQL text need not change.
"""
import re
import sqlite3
import threading
from decimal import Decimal

import psycopg
from psycopg import errors as _pgerr


class Error(sqlite3.OperationalError):
    """A Postgres error wearing sqlite3's coat, so `except sqlite3.Error`
    sites see what they expect."""


class IntegrityError(sqlite3.IntegrityError):
    pass


def _wrap(e: Exception) -> Exception:
    if isinstance(e, (_pgerr.IntegrityError,)):
        return IntegrityError(str(e).splitlines()[0])
    return Error(str(e).splitlines()[0])


# ── the row ──────────────────────────────────────────────────────────────────

def _py(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, memoryview):
        return bytes(v)
    return v


class Row:
    """sqlite3.Row's behaviour: index by name or position, keys(),
    iteration over values, dict(row)."""
    __slots__ = ("_cols", "_vals", "_idx")

    def __init__(self, cols: tuple, idx: dict, vals: tuple):
        self._cols = cols
        self._idx = idx
        self._vals = tuple(_py(v) for v in vals)

    def __getitem__(self, k):
        if isinstance(k, (int, slice)):
            return self._vals[k]
        try:
            return self._vals[self._idx[k]]
        except KeyError:
            try:
                return self._vals[self._idx[k.lower()]]
            except KeyError:
                raise IndexError(f"No item with that key: {k!r}")

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __contains__(self, k):
        return k in self._idx

    def get(self, k, default=None):
        try:
            return self[k]
        except IndexError:
            return default

    def __repr__(self):
        return f"Row({dict(zip(self._cols, self._vals))!r})"

    def __eq__(self, other):
        if isinstance(other, Row):
            return self._vals == other._vals and self._cols == other._cols
        return NotImplemented

    def __hash__(self):
        return hash((self._cols, self._vals))


# ── SQL translation ──────────────────────────────────────────────────────────

def _split_statements(script: str) -> list:
    """Split a script on `;` outside quotes and comments."""
    out, buf, i, n = [], [], 0, len(script)
    in_s = False
    while i < n:
        ch = script[i]
        if in_s:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and script[i + 1] == "'":
                    buf.append("'"); i += 1
                else:
                    in_s = False
        elif ch == "'":
            in_s = True; buf.append(ch)
        elif ch == "-" and i + 1 < n and script[i + 1] == "-":
            j = script.find("\n", i)
            i = n if j < 0 else j
            buf.append("\n"); continue
        elif ch == "/" and i + 1 < n and script[i + 1] == "*":
            j = script.find("*/", i + 2)
            i = n if j < 0 else j + 2
            buf.append(" "); continue
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    stmt = "".join(buf).strip()
    if stmt:
        out.append(stmt)
    return out


def _placeholders(sql: str, with_params: bool = True) -> str:
    """`?` → `%s` outside string literals. When the statement carries
    parameters psycopg reads every `%` as a format directive — inside
    literals too — so each literal `%` becomes `%%`; without parameters
    the text goes through untouched."""
    out, i, n, in_s = [], 0, len(sql), False
    while i < n:
        ch = sql[i]
        if in_s:
            out.append("%%" if (ch == "%" and with_params) else ch)
            if ch == "'":
                in_s = False
        elif ch == "'":
            in_s = True; out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%" if with_params else ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


_TYPE_MAP = [
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY(\s+AUTOINCREMENT)?\b", re.I),
     "BIGSERIAL PRIMARY KEY"),
    (re.compile(r"\bINTEGER\b", re.I), "BIGINT"),
    (re.compile(r"\bREAL\b", re.I), "DOUBLE PRECISION"),
    (re.compile(r"\bBLOB\b", re.I), "BYTEA"),
]
_DDL = re.compile(r"^\s*(CREATE\s+(TABLE|INDEX|UNIQUE\s+INDEX)|ALTER\s+TABLE)\b", re.I)
_VIRTUAL = re.compile(r"^\s*CREATE\s+(VIRTUAL\s+TABLE|TRIGGER)\b", re.I)
_INSERT = re.compile(r"^\s*INSERT\s+(?:OR\s+(IGNORE|REPLACE)\s+)?INTO\s+([\w\"]+)\s*(\(([^)]*)\))?",
                     re.I)
_PRAGMA_INFO = re.compile(r"^\s*PRAGMA\s+table_info\s*\(\s*['\"]?(\w+)['\"]?\s*\)", re.I)
_PRAGMA = re.compile(r"^\s*PRAGMA\b", re.I)
_LIKE = re.compile(r"\bLIKE\b", re.I)
_NOCASE = re.compile(r"([\w.]+)\s+COLLATE\s+NOCASE", re.I)
_BEGIN = re.compile(r"^\s*BEGIN(\s+(IMMEDIATE|DEFERRED|EXCLUSIVE))?\s*$", re.I)
_ROLLBACK = re.compile(r"^\s*ROLLBACK\s*$", re.I)
_COMMIT = re.compile(r"^\s*COMMIT\s*$", re.I)
_LIMIT_NEG = re.compile(r"\bLIMIT\s+-1\b", re.I)
# SQLite's `x IS ?` is a null-safe equals; Postgres spells that
# IS NOT DISTINCT FROM (and `IS NOT ?` the other way round).
_IS_NOT_PARAM = re.compile(r"\bIS\s+NOT\s+\?", re.I)
_IS_PARAM = re.compile(r"\bIS\s+\?", re.I)


def _cast_integer(s: str) -> str:
    """`CAST(x AS INTEGER)` truncates toward zero in SQLite and rounds in
    Postgres; the app means truncation (day buckets, cents). Rewritten
    with a paren-aware scan so `x` may hold its own parentheses."""
    out, i, n = [], 0, len(s)
    rx = re.compile(r"CAST\s*\(", re.I)
    while True:
        m = rx.search(s, i)
        if not m:
            out.append(s[i:]); break
        depth, j = 1, m.end()
        while j < n and depth:
            if s[j] == "(": depth += 1
            elif s[j] == ")": depth -= 1
            j += 1
        inner = s[m.end():j - 1]
        mm = re.match(r"^(.*)\s+AS\s+(INTEGER|INT|BIGINT)\s*$", inner, re.I | re.S)
        out.append(s[i:m.start()])
        if mm:
            out.append(f"sqlite_int({mm.group(1)})")
        else:
            out.append(s[m.start():j])
        i = j
    return "".join(out)


_MASTER = re.compile(r"\bsqlite_master\b", re.I)
_MASTER_VIEW = ("(SELECT table_name AS name, 'table' AS type, table_name AS"
                " tbl_name, '' AS sql FROM information_schema.tables"
                " WHERE table_schema='public') sqlite_master")


def translate(sql: str, with_params: bool = True) -> str:
    s = sql
    if _MASTER.search(s):
        # The catalogue, as the app asks SQLite for it.
        s = _MASTER.sub(_MASTER_VIEW, s)
    if _DDL.match(s):
        for rx, rep in _TYPE_MAP:
            s = rx.sub(rep, s)
    s = _cast_integer(s)
    s = _IS_NOT_PARAM.sub("IS DISTINCT FROM ?", s)
    s = _IS_PARAM.sub("IS NOT DISTINCT FROM ?", s)
    s = _LIKE.sub("ILIKE", s)
    s = _NOCASE.sub(r"lower(\1)", s)
    s = _LIMIT_NEG.sub("LIMIT ALL", s)
    return _placeholders(s, with_params)


# ── functions SQLite has and Postgres does not ───────────────────────────────

SHIMS = """
CREATE OR REPLACE FUNCTION round(v double precision, d integer)
  RETURNS double precision LANGUAGE sql IMMUTABLE AS
  $$ SELECT round(v::numeric, d)::double precision $$;
CREATE OR REPLACE FUNCTION max(a double precision, b double precision)
  RETURNS double precision LANGUAGE sql IMMUTABLE AS $$ SELECT greatest(a, b) $$;
CREATE OR REPLACE FUNCTION max(a bigint, b bigint)
  RETURNS bigint LANGUAGE sql IMMUTABLE AS $$ SELECT greatest(a, b) $$;
CREATE OR REPLACE FUNCTION max(a double precision, b double precision, c double precision)
  RETURNS double precision LANGUAGE sql IMMUTABLE AS $$ SELECT greatest(a, b, c) $$;
CREATE OR REPLACE FUNCTION min(a double precision, b double precision)
  RETURNS double precision LANGUAGE sql IMMUTABLE AS $$ SELECT least(a, b) $$;
CREATE OR REPLACE FUNCTION min(a bigint, b bigint)
  RETURNS bigint LANGUAGE sql IMMUTABLE AS $$ SELECT least(a, b) $$;
CREATE OR REPLACE FUNCTION min(a double precision, b double precision, c double precision)
  RETURNS double precision LANGUAGE sql IMMUTABLE AS $$ SELECT least(a, b, c) $$;
CREATE OR REPLACE FUNCTION sqlite_int(v boolean) RETURNS bigint
  LANGUAGE sql IMMUTABLE AS $$ SELECT CASE WHEN v THEN 1 ELSE 0 END $$;
CREATE OR REPLACE FUNCTION sqlite_int(v double precision) RETURNS bigint
  LANGUAGE sql IMMUTABLE AS $$ SELECT trunc(v)::bigint $$;
CREATE OR REPLACE FUNCTION sqlite_int(v numeric) RETURNS bigint
  LANGUAGE sql IMMUTABLE AS $$ SELECT trunc(v)::bigint $$;
CREATE OR REPLACE FUNCTION sqlite_int(v bigint) RETURNS bigint
  LANGUAGE sql IMMUTABLE AS $$ SELECT v $$;
CREATE OR REPLACE FUNCTION sqlite_int(v text) RETURNS bigint
  LANGUAGE sql IMMUTABLE AS
  $$ SELECT COALESCE(trunc(NULLIF(substring(v from '^\\s*-?\\d+(\\.\\d+)?'), '')::numeric)::bigint, 0) $$;
CREATE OR REPLACE FUNCTION bc_bool_sum_step(acc bigint, v boolean)
  RETURNS bigint LANGUAGE sql IMMUTABLE AS
  $$ SELECT acc + CASE WHEN v THEN 1 ELSE 0 END $$;
DROP AGGREGATE IF EXISTS sum(boolean);
CREATE AGGREGATE sum(boolean) (sfunc = bc_bool_sum_step, stype = bigint, initcond = '0');
CREATE OR REPLACE FUNCTION bc_bool_avg_step(acc bigint[], v boolean)
  RETURNS bigint[] LANGUAGE sql IMMUTABLE AS
  $$ SELECT ARRAY[acc[1] + CASE WHEN v THEN 1 ELSE 0 END, acc[2] + 1] $$;
CREATE OR REPLACE FUNCTION bc_bool_avg_final(acc bigint[])
  RETURNS double precision LANGUAGE sql IMMUTABLE AS
  $$ SELECT CASE WHEN acc[2] = 0 THEN NULL ELSE acc[1]::double precision / acc[2] END $$;
DROP AGGREGATE IF EXISTS avg(boolean);
CREATE AGGREGATE avg(boolean) (sfunc = bc_bool_avg_step, stype = bigint[],
  finalfunc = bc_bool_avg_final, initcond = '{0,0}');
CREATE OR REPLACE FUNCTION bc_gc_step(acc text, v anyelement)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT CASE WHEN v IS NULL THEN acc
     WHEN acc IS NULL THEN v::text ELSE acc || ',' || v::text END $$;
CREATE OR REPLACE FUNCTION bc_gc_step2(acc text, v anyelement, sep text)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT CASE WHEN v IS NULL THEN acc
     WHEN acc IS NULL THEN v::text ELSE acc || sep || v::text END $$;
DROP AGGREGATE IF EXISTS group_concat(anyelement);
CREATE AGGREGATE group_concat(anyelement) (sfunc = bc_gc_step, stype = text);
DROP AGGREGATE IF EXISTS group_concat(anyelement, text);
CREATE AGGREGATE group_concat(anyelement, text) (sfunc = bc_gc_step2, stype = text);
CREATE OR REPLACE FUNCTION bc_json_path(path text) RETURNS text[]
  LANGUAGE sql IMMUTABLE AS
  $$ SELECT string_to_array(regexp_replace(path, '^\\$\\.?', ''), '.') $$;
DROP FUNCTION IF EXISTS json_set(text, text, anyelement);
CREATE OR REPLACE FUNCTION json_set(doc text, path text, val text)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT jsonb_set(COALESCE(NULLIF(doc, ''), '{}')::jsonb, bc_json_path(path),
                      to_jsonb(val), true)::text $$;
CREATE OR REPLACE FUNCTION json_set(doc text, path text, val bigint)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT jsonb_set(COALESCE(NULLIF(doc, ''), '{}')::jsonb, bc_json_path(path),
                      to_jsonb(val), true)::text $$;
CREATE OR REPLACE FUNCTION json_set(doc text, path text, val double precision)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT jsonb_set(COALESCE(NULLIF(doc, ''), '{}')::jsonb, bc_json_path(path),
                      to_jsonb(val), true)::text $$;
CREATE OR REPLACE FUNCTION json_extract(doc text, path text)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT COALESCE(NULLIF(doc, ''), '{}')::jsonb #>> bc_json_path(path) $$;
CREATE OR REPLACE FUNCTION iif(c boolean, a anyelement, b anyelement)
  RETURNS anyelement LANGUAGE sql IMMUTABLE AS
  $$ SELECT CASE WHEN c THEN a ELSE b END $$;
CREATE OR REPLACE FUNCTION instr(h text, n text)
  RETURNS integer LANGUAGE sql IMMUTABLE AS
  $$ SELECT position(n in h) $$;
CREATE OR REPLACE FUNCTION sqlite_fmt(fmt text) RETURNS text LANGUAGE sql
  IMMUTABLE AS $$ SELECT replace(replace(replace(replace(replace(replace(
    replace(replace(replace(replace(fmt, '%Y', 'YYYY'), '%m', 'MM'),
    '%d', 'DD'), '%H', 'HH24'), '%M', 'MI'), '%S', 'SS'), '%j', 'DDD'),
    '%w', 'D'), '%W', 'IW'), '%B', 'FMMonth') $$;
CREATE OR REPLACE FUNCTION strftime(fmt text, ts double precision, mod text)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT CASE WHEN fmt = '%s' THEN floor(ts)::bigint::text
     ELSE to_char(to_timestamp(ts) AT TIME ZONE 'UTC', sqlite_fmt(fmt)) END $$;
CREATE OR REPLACE FUNCTION strftime(fmt text, ts double precision, mod text, mod2 text)
  RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT CASE WHEN fmt = '%s' THEN floor(ts)::bigint::text
     ELSE to_char(CASE WHEN mod2 = 'localtime' THEN to_timestamp(ts)::timestamp
                       ELSE to_timestamp(ts) AT TIME ZONE 'UTC' END, sqlite_fmt(fmt)) END $$;
CREATE OR REPLACE FUNCTION date(ts double precision, mod text)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT to_char(to_timestamp(ts) AT TIME ZONE 'UTC', 'YYYY-MM-DD') $$;
CREATE OR REPLACE FUNCTION date(ts double precision, mod text, mod2 text)
  RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT to_char(CASE WHEN mod2 = 'localtime' THEN to_timestamp(ts)::timestamp
                    ELSE to_timestamp(ts) AT TIME ZONE 'UTC' END, 'YYYY-MM-DD') $$;
CREATE OR REPLACE FUNCTION datetime(ts double precision, mod text, mod2 text)
  RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT to_char(CASE WHEN mod2 = 'localtime' THEN to_timestamp(ts)::timestamp
                    ELSE to_timestamp(ts) AT TIME ZONE 'UTC' END, 'YYYY-MM-DD HH24:MI:SS') $$;
CREATE OR REPLACE FUNCTION strftime(fmt text, ts text)
  RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT CASE WHEN fmt = '%s' THEN floor(extract(epoch from
       CASE WHEN ts = 'now' THEN now() ELSE ts::timestamp END))::bigint::text
     ELSE to_char(CASE WHEN ts = 'now' THEN now() AT TIME ZONE 'UTC'
                       ELSE ts::timestamp END, sqlite_fmt(fmt)) END $$;
CREATE OR REPLACE FUNCTION datetime(ts double precision, mod text)
  RETURNS text LANGUAGE sql IMMUTABLE AS
  $$ SELECT to_char(to_timestamp(ts) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') $$;
CREATE OR REPLACE FUNCTION datetime(ts text)
  RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT to_char(CASE WHEN ts = 'now' THEN now() AT TIME ZONE 'UTC'
                    ELSE ts::timestamp END, 'YYYY-MM-DD HH24:MI:SS') $$;
CREATE OR REPLACE FUNCTION date(ts text)
  RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT to_char(CASE WHEN ts = 'now' THEN now() AT TIME ZONE 'UTC'
                    ELSE ts::timestamp END, 'YYYY-MM-DD') $$;
CREATE OR REPLACE FUNCTION date(ts text, mod text)
  RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT to_char(
       (CASE WHEN ts = 'now' THEN now()::date ELSE ts::date END)
       + CASE WHEN mod ~ '^[+-]?\\d+ (day|days|month|months|year|years)$'
              THEN mod::interval ELSE interval '0' END,
       'YYYY-MM-DD') $$;
CREATE OR REPLACE FUNCTION julianday(ts text)
  RETURNS double precision LANGUAGE sql STABLE AS
  $$ SELECT extract(epoch from CASE WHEN ts = 'now' THEN now()
       ELSE ts::timestamp END) / 86400.0 + 2440587.5 $$;
"""


# ── the server: databases per tenant ─────────────────────────────────────────

_READY: set = set()
_READY_LOCK = threading.Lock()


def _dbname(tenant) -> str:
    t = re.sub(r"[^a-z0-9_]", "_", str(tenant or "legacy").lower())[:50]
    return f"bc_{t}"


def _server_dsn(dsn: str) -> str:
    """The same server, the maintenance database."""
    return re.sub(r"(/)[^/?]*(\?|$)", r"\1postgres\2", dsn, count=1)


def _tenant_dsn(dsn: str, name: str) -> str:
    return re.sub(r"(/)[^/?]*(\?|$)", rf"\1{name}\2", dsn, count=1)


def ensure_database(dsn: str, tenant) -> str:
    """Make the tenant's database if it does not exist, and give it the
    SQLite function shims. Once per process per tenant."""
    name = _dbname(tenant)
    with _READY_LOCK:
        if name in _READY:
            return _tenant_dsn(dsn, name)
    with psycopg.connect(_server_dsn(dsn), autocommit=True) as adm:
        if not adm.execute("SELECT 1 FROM pg_database WHERE datname=%s",
                           (name,)).fetchone():
            adm.execute(f'CREATE DATABASE "{name}"')
    tdsn = _tenant_dsn(dsn, name)
    with psycopg.connect(tdsn, autocommit=True) as con:
        for stmt in _split_statements(SHIMS):
            con.execute(stmt)
    with _READY_LOCK:
        _READY.add(name)
    return tdsn


def drop_database(dsn: str, tenant) -> None:
    name = _dbname(tenant)
    with psycopg.connect(_server_dsn(dsn), autocommit=True) as adm:
        adm.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname=%s AND pid <> pg_backend_pid()", (name,))
        adm.execute(f'DROP DATABASE IF EXISTS "{name}"')
    with _READY_LOCK:
        _READY.discard(name)


# ── the connection ───────────────────────────────────────────────────────────

class Cursor:
    def __init__(self, con, rows, cols, rowcount, lastrowid):
        self._con = con
        self._rows = rows          # list of tuples, or None
        self._cols = cols
        self._idx = {c: i for i, c in enumerate(cols)} if cols else {}
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self._pos = 0
        self.description = [(c, None, None, None, None, None, None)
                            for c in cols] if cols else None

    def _row(self, t):
        return Row(self._cols, self._idx, t)

    def fetchone(self):
        if not self._rows or self._pos >= len(self._rows):
            return None
        r = self._rows[self._pos]
        self._pos += 1
        return self._row(r)

    def fetchall(self):
        if not self._rows:
            return []
        out = [self._row(r) for r in self._rows[self._pos:]]
        self._pos = len(self._rows)
        return out

    def fetchmany(self, n=1):
        if not self._rows:
            return []
        out = [self._row(r) for r in self._rows[self._pos:self._pos + n]]
        self._pos += len(out)
        return out

    def __iter__(self):
        return self

    def __next__(self):
        r = self.fetchone()
        if r is None:
            raise StopIteration
        return r

    def execute(self, sql, params=()):
        return self._con.execute(sql, params)

    def close(self):
        pass


class Connection:
    """The sqlite3.Connection surface the app uses."""

    def __init__(self, dsn: str):
        self._pg = psycopg.connect(dsn, autocommit=True)
        self._in_tx = False
        self._keys: dict = {}          # table -> list of key column tuples
        self._cols: dict = {}          # table -> set of column names
        self.row_factory = None
        self.total_changes = 0
        self._lock = threading.Lock()

    # -- transactions: statement-level atomicity, like SQLite --
    def _begin(self):
        if not self._in_tx:
            self._pg.execute("BEGIN")
            self._in_tx = True

    def commit(self):
        with self._lock:
            if self._in_tx:
                self._pg.execute("COMMIT")
                self._in_tx = False

    def rollback(self):
        with self._lock:
            if self._in_tx:
                self._pg.execute("ROLLBACK")
                self._in_tx = False

    def close(self):
        try:
            if self._in_tx:
                self._pg.execute("ROLLBACK")
        except Exception:                                    # noqa: BLE001
            pass
        self._pg.close()

    @property
    def in_transaction(self):
        return self._in_tx

    # -- catalogue helpers --
    def _columns(self, table: str) -> set:
        t = table.strip('"').lower()
        if t not in self._cols:
            self._begin()
            rows = self._guarded("SELECT column_name FROM information_schema.columns"
                                 " WHERE table_name=%s", (t,))
            self._cols[t] = {r[0] for r in rows}
        return self._cols[t]

    def _keys_of(self, table: str) -> list:
        t = table.strip('"').lower()
        if t not in self._keys:
            self._begin()
            rows = self._guarded(
                "SELECT c.conname, array_agg(a.attname ORDER BY x.n)"
                " FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid"
                " JOIN LATERAL unnest(c.conkey) WITH ORDINALITY x(attnum, n)"
                "  ON true"
                " JOIN pg_attribute a ON a.attrelid=r.oid AND a.attnum=x.attnum"
                " WHERE r.relname=%s AND c.contype IN ('p','u')"
                " GROUP BY c.conname, c.contype ORDER BY c.contype", (t,))
            self._keys[t] = [tuple(r[1]) for r in rows]
        return self._keys[t]

    def _raw(self, sql, params=()):
        return self._pg.execute(sql, params)

    # -- the translation of one statement --
    def _prepare(self, sql: str, params=()):
        """(sql, lastrowid_wanted, table, explicit_id) for one statement."""
        s = sql.strip()
        m = _INSERT.match(s)
        want_id, table, explicit_id = False, None, False
        if m:
            mode, table = (m.group(1) or "").upper(), m.group(2)
            cols = [c.strip().strip('"').lower() for c in (m.group(4) or "").split(",")] \
                if m.group(4) else []
            has_conflict = re.search(r"\bON\s+CONFLICT\b", s, re.I) is not None
            if mode == "IGNORE":
                s = _INSERT.sub(lambda mm: f"INSERT INTO {mm.group(2)}"
                                + (f"({mm.group(4)})" if mm.group(4) else ""), s, count=1)
                if not has_conflict:
                    s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
            elif mode == "REPLACE":
                s = _INSERT.sub(lambda mm: f"INSERT INTO {mm.group(2)}"
                                + (f"({mm.group(4)})" if mm.group(4) else ""), s, count=1)
                if not has_conflict:
                    key = None
                    for k in self._keys_of(table):
                        if cols and set(k) <= set(cols):
                            key = k
                            break
                    if key is None:
                        ks = self._keys_of(table)
                        key = ks[0] if ks else None
                    if key:
                        rest = [c for c in cols if c not in key]
                        if rest:
                            s = (s.rstrip().rstrip(";") + f" ON CONFLICT ({','.join(key)})"
                                 + " DO UPDATE SET "
                                 + ", ".join(f"{c}=EXCLUDED.{c}" for c in rest))
                        else:
                            s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
            tcols = self._columns(table)
            if "id" in tcols and not re.search(r"\bRETURNING\b", s, re.I):
                s = s.rstrip().rstrip(";") + " RETURNING id"
                want_id = True
            explicit_id = "id" in cols
        return translate(s, bool(params)), want_id, table, explicit_id

    def _pragma_info(self, table: str):
        self._begin()
        rows = self._guarded(
            "SELECT ordinal_position-1, column_name, data_type,"
            " CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END, column_default"
            " FROM information_schema.columns WHERE table_name=%s"
            " ORDER BY ordinal_position", (table.lower(),))
        keys = self._keys_of(table)
        pk = set(keys[0]) if keys else set()
        cols = ("cid", "name", "type", "notnull", "dflt_value", "pk")
        out = [tuple(r) + (1 if r[1] in pk else 0,) for r in rows]
        return Cursor(self, out, cols, len(out), None)

    def execute(self, sql: str, params=()):
        with self._lock:
            return self._execute(sql, params)

    def _execute(self, sql: str, params=()):
        s = sql.strip()
        if _PRAGMA_INFO.match(s):
            return self._pragma_info(_PRAGMA_INFO.match(s).group(1))
        if _PRAGMA.match(s):
            return Cursor(self, [], (), 0, None)
        if _BEGIN.match(s):
            self._begin()
            return Cursor(self, None, (), 0, None)
        if _ROLLBACK.match(s):
            self.rollback() if not self._lock.locked() else self._rollback_locked()
            return Cursor(self, None, (), 0, None)
        if _COMMIT.match(s):
            self._commit_locked()
            return Cursor(self, None, (), 0, None)
        if _VIRTUAL.match(s):
            raise Error("virtual tables and triggers are SQLite's")
        if isinstance(params, dict):
            raise Error("named parameters are not supported here")
        params = tuple(int(p) if isinstance(p, bool) else p for p in params)
        pgsql, want_id, table, explicit_id = self._prepare(s, params)
        self._begin()
        self._pg.execute("SAVEPOINT bc")
        try:
            cur = self._pg.execute(pgsql, params or None)
        except Exception as e:                               # noqa: BLE001
            try:
                self._pg.execute("ROLLBACK TO SAVEPOINT bc")
            except Exception:                                # noqa: BLE001
                pass
            raise _wrap(e) from None
        self._pg.execute("RELEASE SAVEPOINT bc")
        rows, cols, lastrowid = None, (), None
        if cur.description:
            cols = tuple(d.name for d in cur.description)
            rows = cur.fetchall()
            if want_id:
                lastrowid = rows[0][0] if rows else None
                rows, cols = None, ()
        rowcount = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        if want_id or table:
            self.total_changes += max(rowcount, 0)
        if explicit_id and table:
            # An insert that names its own id leaves the sequence behind
            # it; move the sequence past it. In its own savepoint: a text
            # primary key has no sequence, and a failed statement outside
            # a savepoint poisons the whole transaction.
            self._guarded(
                "SELECT setval(seq, GREATEST((SELECT COALESCE(MAX(id),1)"
                " FROM " + table + "), 1)) FROM"
                " (SELECT pg_get_serial_sequence(%s, 'id') AS seq) q"
                " WHERE seq IS NOT NULL", (table,))
        return Cursor(self, rows, cols, rowcount, lastrowid)

    def _guarded(self, sql, params=()):
        """A statement of our own, inside a savepoint, whose failure is
        nobody's business — never the app's transaction."""
        self._pg.execute("SAVEPOINT bc_g")
        try:
            cur = self._pg.execute(sql, params or None)
            rows = cur.fetchall() if cur.description else []
            self._pg.execute("RELEASE SAVEPOINT bc_g")
            return rows
        except Exception:                                    # noqa: BLE001
            try:
                self._pg.execute("ROLLBACK TO SAVEPOINT bc_g")
            except Exception:                                # noqa: BLE001
                pass
            return []

    def _rollback_locked(self):
        if self._in_tx:
            self._pg.execute("ROLLBACK")
            self._in_tx = False

    def _commit_locked(self):
        if self._in_tx:
            self._pg.execute("COMMIT")
            self._in_tx = False

    def executemany(self, sql: str, seq):
        cur = None
        for params in seq:
            cur = self.execute(sql, params)
        return cur or Cursor(self, None, (), 0, None)

    def executescript(self, script: str):
        with self._lock:
            for stmt in _split_statements(script):
                if _VIRTUAL.match(stmt):
                    raise Error("virtual tables and triggers are SQLite's")
                self._execute(stmt)
            self._commit_locked()
        return Cursor(self, None, (), 0, None)

    def cursor(self):
        return _CursorProxy(self)

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.commit()
        else:
            self.rollback()
        return False


class _CursorProxy:
    def __init__(self, con):
        self._con = con
        self._last = None

    def execute(self, sql, params=()):
        self._last = self._con.execute(sql, params)
        return self._last

    def fetchone(self):
        return self._last.fetchone() if self._last else None

    def fetchall(self):
        return self._last.fetchall() if self._last else []

    def close(self):
        pass

    @property
    def lastrowid(self):
        return self._last.lastrowid if self._last else None

    @property
    def rowcount(self):
        return self._last.rowcount if self._last else 0


def connect(dsn: str, tenant) -> Connection:
    return Connection(ensure_database(dsn, tenant))


# ── a backup, the Postgres way ───────────────────────────────────────────────

def pg_dump_path():
    """pg_dump on the PATH, or the one the embedded server ships."""
    import shutil
    from pathlib import Path as _P
    exe = shutil.which("pg_dump")
    if exe:
        return exe
    try:
        import pgserver
        cand = _P(pgserver.__file__).parent / "pginstall" / "bin" / "pg_dump"
        return str(cand) if cand.exists() else None
    except ImportError:
        return None


def dump(dsn: str, tenant) -> bytes:
    """The tenant's database as a plain-SQL pg_dump — readable, and
    restorable with `psql -f`; the counterpart of the .db file a SQLite
    tenant downloads."""
    import subprocess
    import tempfile
    exe = pg_dump_path()
    if not exe:
        raise Error("pg_dump is not installed on this node")
    tdsn = _tenant_dsn(dsn, _dbname(tenant))
    with tempfile.TemporaryDirectory() as td:
        out = f"{td}/backup.sql"
        r = subprocess.run([exe, "--format=plain", "--no-owner",
                            "--dbname", tdsn, "--file", out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Error(f"pg_dump failed: {r.stderr.strip()[:200]}")
        with open(out, "rb") as f:
            return f.read()
