"""Files somewhere every node can reach.

An upload used to be a path under the tenant's directory on the node
that took it. That is fine while a tenant lives on one machine and it is
exactly wrong the moment two machines serve the same tenant: the second
one has the row and not the file. So a tenant's files can live in an
object store instead — any S3-compatible one: AWS S3, Backblaze B2,
Cloudflare R2, MinIO on a box of your own — and the app reads and writes
them through here, never through a path.

`store()` says which: `{"kind": "local"}` (the default, the directory as
before) or `{"kind": "s3", "endpoint": ..., "bucket": ..., "region": ...,
"key": ..., "secret": ..., "prefix": ...}` from the install's config.json
(the `blobs` key) or the environment (BC_BLOBS as JSON). Keys are the
same relative paths the rows already hold (`xx/<token>.<ext>`), so a
tenant moved to object storage keeps every row it had.

The S3 client is a hundred lines of Signature V4 over urllib rather than
a dependency: four verbs, no retries to configure, nothing to pin.
"""
import datetime as _dt
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import tenancy


def store() -> dict:
    raw = os.environ.get("BC_BLOBS")
    if raw:
        try:
            st = json.loads(raw)
            if isinstance(st, dict) and st.get("kind"):
                return st
        except ValueError:
            pass
    try:
        from . import config
        st = config.load().get("blobs") or {}
    except Exception:                                        # noqa: BLE001
        st = {}
    return st if st.get("kind") else {"kind": "local"}


def uploads_root() -> str:
    return str(tenancy.data_dir() / "uploads")


# ── local ────────────────────────────────────────────────────────────────────

def _local_path(rel: str) -> str:
    root = os.path.abspath(uploads_root())
    target = os.path.abspath(os.path.join(root, rel))
    if not target.startswith(root + os.sep):
        raise ValueError("outside the uploads root")
    return target


class Local:
    kind = "local"

    def put(self, rel: str, data: bytes, mime: str = "") -> None:
        dest = _local_path(rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        with open(tmp, "wb") as f:              # write-then-rename: no half file
            f.write(data)
        os.replace(tmp, dest)

    def get(self, rel: str):
        try:
            with open(_local_path(rel), "rb") as f:
                return f.read()
        except (OSError, ValueError):
            return None

    def exists(self, rel: str) -> bool:
        try:
            return os.path.isfile(_local_path(rel))
        except ValueError:
            return False

    def delete(self, rel: str) -> bool:
        try:
            os.unlink(_local_path(rel))
            return True
        except (OSError, ValueError):
            return False

    def path(self, rel: str):
        """A real file on disk, for FileResponse; None elsewhere."""
        p = _local_path(rel)
        return p if os.path.isfile(p) else None


# ── S3-compatible, Signature V4 ──────────────────────────────────────────────

def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


class S3:
    kind = "s3"

    def __init__(self, cfg: dict):
        self.endpoint = cfg["endpoint"].rstrip("/")
        self.bucket = cfg["bucket"]
        self.region = cfg.get("region") or "us-east-1"
        self.key = cfg.get("key") or ""
        self.secret = cfg.get("secret") or ""
        self.prefix = (cfg.get("prefix") or "").strip("/")
        # path-style (endpoint/bucket/key) works everywhere; virtual-host
        # style needs DNS that MinIO on a box does not have.
        self.path_style = bool(cfg.get("path_style", True))
        self.timeout = float(cfg.get("timeout", 20))

    def _key(self, rel: str) -> str:
        tid = tenancy.CURRENT.get() or "legacy"
        parts = [p for p in (self.prefix, tid, rel) if p]
        return "/".join(parts)

    def _url(self, key: str) -> str:
        q = urllib.parse.quote(key, safe="/")
        if self.path_style:
            return f"{self.endpoint}/{self.bucket}/{q}"
        u = urllib.parse.urlsplit(self.endpoint)
        return f"{u.scheme}://{self.bucket}.{u.netloc}/{q}"

    def _signed(self, method: str, key: str, body: bytes = b"",
                mime: str = "") -> urllib.request.Request:
        url = self._url(key)
        u = urllib.parse.urlsplit(url)
        now = _dt.datetime.now(_dt.timezone.utc)
        amz = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        payload = _sha256(body)
        headers = {"host": u.netloc, "x-amz-content-sha256": payload,
                   "x-amz-date": amz}
        if mime and method == "PUT":
            headers["content-type"] = mime
        signed = ";".join(sorted(headers))
        canon = "\n".join([method, u.path or "/", u.query,
                           "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)),
                           signed, payload])
        scope = f"{day}/{self.region}/s3/aws4_request"
        sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, _sha256(canon.encode())])
        k = _hmac(("AWS4" + self.secret).encode(), day)
        k = _hmac(k, self.region); k = _hmac(k, "s3"); k = _hmac(k, "aws4_request")
        sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
        auth = (f"AWS4-HMAC-SHA256 Credential={self.key}/{scope},"
                f" SignedHeaders={signed}, Signature={sig}")
        req = urllib.request.Request(url, data=body if method == "PUT" else None,
                                     method=method)
        for hk, hv in headers.items():
            if hk != "host":
                req.add_header(hk, hv)
        req.add_header("Authorization", auth)
        return req

    def _do(self, method: str, rel: str, body: bytes = b"", mime: str = ""):
        req = self._signed(method, self._key(rel), body, mime)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read() if method == "GET" else b""
        except urllib.error.HTTPError as e:
            return e.code, b""

    def put(self, rel: str, data: bytes, mime: str = "") -> None:
        code, _ = self._do("PUT", rel, data, mime or "application/octet-stream")
        if code not in (200, 201, 204):
            raise OSError(f"object store refused the upload ({code})")

    def get(self, rel: str):
        code, body = self._do("GET", rel)
        return body if code == 200 else None

    def exists(self, rel: str) -> bool:
        code, _ = self._do("HEAD", rel)
        return code == 200

    def delete(self, rel: str) -> bool:
        code, _ = self._do("DELETE", rel)
        return code in (200, 204)

    def path(self, rel: str):
        return None


_S3: dict = {}


def driver():
    st = store()
    if st.get("kind") == "s3":
        k = json.dumps(st, sort_keys=True)
        if k not in _S3:
            _S3[k] = S3(st)
        return _S3[k]
    return Local()


# ── the four verbs the app uses ──────────────────────────────────────────────

def put(rel: str, data: bytes, mime: str = "") -> None:
    driver().put(rel, data, mime)


def get(rel: str):
    return driver().get(rel)


def exists(rel: str) -> bool:
    return driver().exists(rel)


def delete(rel: str) -> bool:
    return driver().delete(rel)


def local_path(rel: str):
    return driver().path(rel)


def migrate_local_to_store(con=None, table: str = "learning_materials",
                           column: str = "path") -> dict:
    """Push every file the rows name from this node's disk into the
    object store, once. Files already there are skipped; files the disk
    has lost are reported, not invented."""
    from . import db
    own = con is None
    con = con or db.connect()
    d = driver()
    out = {"pushed": 0, "present": 0, "missing": 0}
    if d.kind != "s3":
        return {**out, "note": "the store is local; nothing to push"}
    try:
        for r in con.execute(f"SELECT DISTINCT {column} FROM {table}"):
            rel = r[0]
            if not rel:
                continue
            if d.exists(rel):
                out["present"] += 1
                continue
            try:
                with open(_local_path(rel), "rb") as f:
                    data = f.read()
            except (OSError, ValueError):
                out["missing"] += 1
                continue
            d.put(rel, data)
            out["pushed"] += 1
    finally:
        if own:
            con.close()
    return out
