"""A Model Context Protocol server in front of one Business Control install.

Speaks JSON-RPC 2.0 over stdin and stdout, one message per line, which is
what a local MCP client launches and talks to. Written directly rather
than against a library for the same reason the rest of this repo writes
its own wire formats: it is a hundred lines of protocol, and a dependency
that has to be installed before an operator can try this is a dependency
that stops them trying it.

    BC_MCP_URL     where the install answers (default http://127.0.0.1:8860)
    BC_MCP_HOST    Host header, when one address serves many tenants
    BC_MCP_KEY     an API key minted in ops, Integrations, API keys
    BC_MCP_WRITES  set to 1 to offer the tools that change records

**stdout carries protocol and nothing else.** A stray print is a parse
error at the client and a server that appears to hang, so every human
word in this file goes to stderr.

The key is the whole of the security here, and it is the same key the
app already understands: bound to an account, scoped read or write,
revocable, refused the moment the capability lapses. Two consequences
worth stating plainly. A read key makes every write tool fail at the
front door no matter what this file offers, which is the belt to
BC_MCP_WRITES's braces. And binding the key to a narrow account is how
you decide what an agent can reach — not by trusting the model, and not
by trusting this list, but by handing it credentials that cannot do the
thing you are worried about.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import tools as T

# The revision of the protocol this speaks. A client asking for another
# is answered in its own: the handshake is version-negotiated and every
# revision so far has been compatible for a server as small as this one.
PROTOCOL = "2025-06-18"
SERVER = {"name": "business-control", "version": "1.0.0"}
TIMEOUT = 30
# A tool result is read into a context window, so a list of every order
# ever placed is not a helpful answer. Trimmed, and SAID to be trimmed —
# silently truncated JSON is how a model concludes a business has four
# customers.
MAX_CHARS = 24000


def log(msg: str) -> None:
    print(f"[business-control mcp] {msg}", file=sys.stderr, flush=True)


def _cfg() -> dict:
    return {
        "url": (os.environ.get("BC_MCP_URL") or "http://127.0.0.1:8860").rstrip("/"),
        "host": os.environ.get("BC_MCP_HOST", ""),
        "key": os.environ.get("BC_MCP_KEY", ""),
        "writes": os.environ.get("BC_MCP_WRITES", "") in ("1", "true", "yes"),
    }


def offered(cfg: dict) -> list:
    return [t for t in T.TOOLS if cfg["writes"] or not t.get("write")]


# ---------- calling the business ----------

def call_api(cfg: dict, tool: dict, args: dict) -> tuple:
    """(ok, payload-or-message). Never raises: a failed call is an answer
    the model should read and act on, not a crashed server."""
    path = tool["path"]
    for k in (tool.get("path_params") or {}):
        if k not in args:
            return False, f"{k} is needed"
        path = path.replace("{" + k + "}", urllib.parse.quote(str(args[k])))

    query = {k: args[k] for k in (tool.get("query") or {})
             if args.get(k) not in (None, "")}
    url = cfg["url"] + path + ("?" + urllib.parse.urlencode(query) if query else "")

    body = None
    headers = {"Accept": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = "Bearer " + cfg["key"]
    if cfg["host"]:
        headers["Host"] = cfg["host"]
    if tool.get("body"):
        payload = {k: args[k] for k in tool["body"] if k in args}
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, method=tool["method"],
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        if e.code in (401, 403):
            return False, (f"{e.code}: {detail}. This key acts as one "
                           "account and is held to that account's "
                           "permissions — call bc_whoami to see whose.")
        return False, f"{e.code}: {detail}"
    except urllib.error.URLError as e:
        return False, (f"could not reach {cfg['url']}: {e.reason}. Is the "
                       "install running, and is BC_MCP_URL right?")
    except OSError as e:                                     # noqa: BLE001
        return False, f"could not reach {cfg['url']}: {e}"
    try:
        return True, json.loads(raw)
    except ValueError:
        return True, raw


def run_tool(cfg: dict, name: str, args: dict) -> tuple:
    tool = T.by_name().get(name)
    if tool is None:
        return False, f"no tool called {name!r}"
    if tool.get("write") and not cfg["writes"]:
        return False, (f"{name} changes records, and this server was "
                       "started read-only. Whoever runs it can set "
                       "BC_MCP_WRITES=1 and restart.")
    missing = [k for k in (tool.get("required") or []) if k not in args]
    if missing:
        return False, f"missing: {', '.join(missing)}"
    ok, payload = call_api(cfg, tool, args)
    if not ok:
        return False, payload
    text = payload if isinstance(payload, str) else json.dumps(
        payload, indent=1, default=str)
    if len(text) > MAX_CHARS:
        text = (text[:MAX_CHARS] + f"\n\n[trimmed at {MAX_CHARS} characters. "
                "This is not the whole answer — narrow the question, or ask "
                "for a summary route instead of a list.]")
    return True, text


# ---------- the protocol ----------

def handle(cfg: dict, msg: dict):
    """A response dict, or None for a notification that wants no reply."""
    method = msg.get("method", "")
    mid = msg.get("id")
    params = msg.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": code, "message": message}}

    if method == "initialize":
        asked = (params.get("protocolVersion") or "").strip()
        return ok({"protocolVersion": asked or PROTOCOL,
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER,
                   "instructions":
                       "One business, running on Business Control. Reading "
                       "is free; call bc_whoami first, because every answer "
                       "is shaped by which account this key acts as. Money, "
                       "public replies and anything irreversible are "
                       "deliberately not offered here — describe what "
                       "should happen and let a person do it."})

    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [
            {"name": t["name"], "description": T.description_for(t),
             "inputSchema": T.schema_for(t)} for t in offered(cfg)]})
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        good, text = run_tool(cfg, name, args)
        # A refusal is a RESULT with isError, not a JSON-RPC error: the
        # model has to read it to do anything useful about it, and a
        # protocol error is the client's problem rather than the model's.
        return ok({"content": [{"type": "text", "text": text}],
                   "isError": not good})
    # Answered rather than refused: clients probe for these whether or not
    # the handshake offered them, and an error in a log looks like a fault.
    if method in ("resources/list", "resources/templates/list"):
        return ok({"resources": [], "resourceTemplates": []})
    if method == "prompts/list":
        return ok({"prompts": []})
    if mid is None:
        return None
    return err(-32601, f"no method {method!r}")


def main() -> int:
    cfg = _cfg()
    if not cfg["key"]:
        log("no BC_MCP_KEY set — every call will be refused by the install. "
            "Mint one in ops under Integrations, API keys.")
    log(f"{cfg['url']}"
        + (f" as {cfg['host']}" if cfg["host"] else "")
        + f", {len(offered(cfg))} tools, "
        + ("writes ON" if cfg["writes"] else "read-only"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "not JSON"}}) + "\n")
            sys.stdout.flush()
            continue
        try:
            out = handle(cfg, msg)
        except Exception as e:                               # noqa: BLE001
            # One bad message must not take the server down: the client
            # would show it as a crashed integration rather than as the
            # single failed call it is.
            log(f"error handling {msg.get('method')!r}: {e}")
            out = {"jsonrpc": "2.0", "id": msg.get("id"),
                   "error": {"code": -32603, "message": str(e)}}
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
    return 0
