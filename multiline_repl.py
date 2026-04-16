# ---------------------------------------------------------------------------
# OMEGA — A Lisp interpreter in Python
# ---------------------------------------------------------------------------

from prompt_toolkit import PromptSession
import sys, re, os, math, json, hashlib, traceback, shutil
from functools import reduce as py_reduce

# ===========================================================================
# PATHS & CONFIG
# ===========================================================================

_DEFAULT_HOME = os.path.expanduser("~/.omega")
_PATHS: dict = {
    "omega_home":  os.getenv("OMEGA_HOME",        _DEFAULT_HOME),
    "store_path":  os.getenv("OMEGA_STORE_PATH",  ""),
    "config_path": os.getenv("OMEGA_CONFIG_PATH", ""),
}

def _resolve_derived() -> None:
    if not _PATHS["store_path"]:
        _PATHS["store_path"]  = os.path.join(_PATHS["omega_home"], "store")
    if not _PATHS["config_path"]:
        _PATHS["config_path"] = os.path.join(_PATHS["omega_home"], "config.json")

def get_omega_home()  -> str: return _PATHS["omega_home"]
def get_store_path()  -> str: return _PATHS["store_path"]
def get_config_path() -> str: return _PATHS["config_path"]

def _ensure_dirs() -> None:
    os.makedirs(get_store_path(), exist_ok=True)
    os.makedirs(os.path.dirname(get_config_path()), exist_ok=True)

def _load_json_safe(path: str) -> dict:
    if not os.path.exists(path): return {}
    try:
        with open(path) as f: return json.load(f)
    except Exception: return {}

def save_config(data: dict) -> str:
    cfg = get_config_path()
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    try:
        cur = _load_json_safe(cfg)
        cur.update(data)
        tmp = cfg + ".tmp"
        with open(tmp, "w") as f: json.dump(cur, f, indent=4)
        os.replace(tmp, cfg)
        return f"Configuration updated at {cfg}"
    except Exception as e:
        return f"Error saving config: {e}"

def load_config() -> dict:
    return _load_json_safe(get_config_path())

def update_omega_home(new_path: str) -> str:
    resolved  = os.path.abspath(os.path.expanduser(new_path))
    old_home  = _PATHS["omega_home"]
    if _PATHS["store_path"].startswith(old_home):
        _PATHS["store_path"]  = os.path.join(resolved, "store")
    if _PATHS["config_path"].startswith(old_home):
        _PATHS["config_path"] = os.path.join(resolved, "config.json")
    _PATHS["omega_home"] = resolved
    _resolve_derived(); _ensure_dirs()
    save_config({"omega_home": resolved,
                 "store_path": get_store_path(),
                 "config_path": get_config_path()})
    return f"OMEGA_HOME moved to: {resolved}"

def update_store_path(new_path: str) -> str:
    resolved = os.path.abspath(os.path.expanduser(new_path))
    _PATHS["store_path"] = resolved
    os.makedirs(resolved, exist_ok=True)
    save_config({"store_path": resolved})
    return f"Store path updated to {resolved}"

def update_config_path(new_path: str) -> str:
    resolved = os.path.abspath(os.path.expanduser(new_path))
    old_cfg  = get_config_path()
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    if os.path.exists(old_cfg) and old_cfg != resolved:
        shutil.copy2(old_cfg, resolved)
    _PATHS["config_path"] = resolved
    save_config({"config_path": resolved})
    return f"Config path redirected to: {resolved}"

def _bootstrap_paths() -> None:
    """Restore persisted path overrides from config before anything else runs."""
    _resolve_derived()
    cfg = _load_json_safe(get_config_path())
    if not os.getenv("OMEGA_HOME")        and "omega_home"  in cfg: _PATHS["omega_home"]  = cfg["omega_home"]
    if not os.getenv("OMEGA_STORE_PATH")  and "store_path"  in cfg: _PATHS["store_path"]  = cfg["store_path"]
    if not os.getenv("OMEGA_CONFIG_PATH") and "config_path" in cfg:
        _PATHS["config_path"] = cfg["config_path"]
        # Phase 2: re-read from the redirected location
        cfg2 = _load_json_safe(cfg["config_path"])
        for key in ("omega_home", "store_path", "config_path"):
            if key in cfg2: _PATHS[key] = cfg2[key]
    _resolve_derived(); _ensure_dirs()

_bootstrap_paths()

# ===========================================================================
# RUNTIME CONSTANTS
# ===========================================================================

SKIP_SIGNAL  = object()          # sentinel: skip this token/value
GENSYM_COUNT = 0
PROMPT       = "λ > "
CONTINUATION = "... "
session      = PromptSession()
_DEBUG_MODE  = [False]   # mutable: [True] = show Python tracebacks, [False] = clean only

def _make_debug_toggle(*args):
    """(debug-mode) → current bool; (debug-mode true/false) → set and return ok"""
    if not args:
        return _DEBUG_MODE[0]
    _DEBUG_MODE[0] = bool(args[0])
    return Symbol("ok")

# ===========================================================================
# CORE TYPES
# ===========================================================================

class Symbol(str):
    """
    A Lisp symbol — a bare identifier that looks itself up in the environment.
    Subclasses str so symbol names can be compared and used as dict keys directly,
    but is never confused with StringLiteral.
    """
    pass

class StringLiteral(str):
    """
    A Lisp string literal — a value written as "hello" in source.
    Wraps the *content* (without outer quotes) as a str subclass so
    the rest of the interpreter can still call str operations on it,
    but isinstance(x, StringLiteral) always unambiguously identifies it.

    The old representation kept outer quotes: '"hello"' as a plain str.
    StringLiteral("hello") replaces that — the outer quotes are gone.
    eval_node no longer needs to strip them; serialization re-adds them.
    """
    pass

class Lambda:
    """A user-defined function (closure)."""
    def __init__(self, params, body, env, required_effects=None, name=None,  source = None):
        self.params           = params
        self.body             = body
        self.env              = env
        self.required_effects = required_effects or []
        self.name = name
        self.source = source
    def __repr__(self):
        eff = f" :effects {self.required_effects}" if self.required_effects else ""
        return f"<Lambda ({' '.join(str(p) for p in self.params)}){eff}>"

class Macro:
    """
    A syntax transformer.  Unlike Lambda, a Macro receives its arguments as
    raw, unevaluated AST and must return a new AST that the evaluator then runs.
    Think of a Macro as a compile-time function over code.

    Lambda  → evaluate args first, then call the body with values.
    Macro   → pass raw AST to body, body produces new AST, evaluate that.
    """
    def __init__(self, params, body, env):
        self.params = params
        self.body   = body
        self.env    = env
    def __repr__(self):
        return f"<Macro ({' '.join(str(p) for p in self.params)})>"

class TailCall:
    """Trampoline signal: evaluate expr in env instead of returning."""
    def __init__(self, expr, env):
        self.expr = expr
        self.env  = env

# ===========================================================================
# DELIMITED CONTINUATIONS  (shift / reset)
# ===========================================================================
#
# Design: two-phase exception-based shift/reset.
#
# PHASE 1 — Capture:
#   (shift k body) evaluates body with k=_Fwd() (a proxy), then raises
#   _ShiftAbort(fwd, body_val, k_invoked=False).
#   As this exception unwinds through function-call frames, each frame that
#   was mid-arg-evaluation appends itself to the fwd's context chain and
#   re-raises with the new abort_value = frame_replay(old_abort_value).
#   reset catches _ShiftAbort and returns abort_value.
#
# PHASE 2 — Resume:
#   After Phase 1, fwd.replay_chain is a list of Python closures,
#   innermost first.  Calling (k v) chains them: k(v) = chain[-1](chain[-2](...chain[0](v)...))
#   If k was invoked INSIDE the body (before Phase 1 completes), _KInvoked
#   propagates through the same frames and each frame applies itself, returning
#   the fully-applied result directly (no exception needed).
#
# Semantics:
#   (reset E)            — establish boundary; return E's value
#   (shift k B)          — capture delimited continuation into k; run B; abort to reset
#   (k v)                — resume: apply captured context to v

class _ShiftAbort(BaseException):
    """Abort signal from (shift k body) propagating to (reset ...)."""
    __slots__ = ('fwd', 'abort_value', 'k_invoked')
    def __init__(self, fwd, abort_value, k_invoked=False):
        self.fwd         = fwd
        self.abort_value = abort_value
        self.k_invoked   = k_invoked   # True only when (k v) was called in body


class _KInvoked(BaseException):
    """(k v) called inside shift body BEFORE context is fully captured.
    Propagates through call frames; each frame applies its context."""
    __slots__ = ('fwd', 'applied_value')
    def __init__(self, fwd, applied_value):
        self.fwd           = fwd
        self.applied_value = applied_value  # grows as frames apply themselves


class _Fwd:
    """
    Mutable proxy representing the continuation k during capture (Phase 1).
    replay_chain is populated by frame handlers as _ShiftAbort unwinds.
    After Phase 1 (_capturing=False), resume() runs the captured chain.
    """
    def __init__(self):
        self.replay_chain = []
        self._real_cont   = None
        self._capturing   = True
        self._used        = False
        self._multi_shot  = False
        self.name         = "continuation"

    def _apply_chain(self, value):
        for fn in self.replay_chain:
            value = fn(value)
        return value

    def _make_real(self, multi_shot=False):
        if self._real_cont is None or multi_shot:
            chain = list(self.replay_chain)
            def replay(v, ch=chain):
                result = v
                for fn in ch:
                    result = fn(result)
                return result
            # Inner Continuation is always multi-shot; _Fwd controls one-shot behavior
            self._real_cont = Continuation(replay, multi_shot=True)
        return self._real_cont

    def _apply_chain_composing(self, value):
        for i, fn in enumerate(self.replay_chain):
            try:
                value = fn(value)
            except _ShiftAbort as sa:
                remaining = self.replay_chain[i+1:]
                if remaining:
                    def _rem(v, r=remaining):
                        for f in r: v = f(v)
                        return v
                    sa.fwd.replay_chain.append(_rem)
                sa.fwd._capturing = False; sa.fwd._make_real()
                return sa.abort_value
        return value

    def resume(self, value):
        if self._capturing:
            raise _KInvoked(self, value)
        if self._real_cont is None:
            self._make_real()
        if not self._multi_shot:
            if self._used:
                raise RuntimeError(
                    "One-shot continuation invoked more than once. "
                    "Wrap with (multi-shot! k) to allow reuse.")
            self._used = True
        return self._apply_chain_composing(value)

    def __call__(self, *args):
        return self.resume(args[0] if args else None)

    def __repr__(self):
        return "<Continuation one-shot>"


class Continuation:
    """
    First-class delimited continuation.  Calling it resumes the computation.
    One-shot by default; (multi-shot! k) returns a reusable copy.
    """
    def __init__(self, replay_fn, multi_shot=False):
        self._replay     = replay_fn
        self._multi_shot = multi_shot
        self._used       = False
        self.name        = "continuation"

    def resume(self, value):
        if self._used and not self._multi_shot:
            raise RuntimeError(
                "One-shot continuation invoked more than once. "
                "Wrap with (multi-shot! k) to allow reuse.")
        if not self._multi_shot:
            self._used = True
        return self._replay(value)

    def __call__(self, *args):
        return self.resume(args[0] if args else None)

    def __repr__(self):
        mode = "multi-shot" if self._multi_shot else "one-shot"
        return f"<Continuation {mode}>"


def _make_multi_shot(k):
    if isinstance(k, _Fwd):
        k._multi_shot = True   # allow repeated calls on this proxy
        return k
    if not isinstance(k, Continuation):
        raise TypeError(f"multi-shot! expects a continuation, got {type(k).__name__}")
    return Continuation(k._replay, multi_shot=True)


def _is_continuation(x):
    return isinstance(x, (Continuation, _Fwd))

class Resource:
    """An optionally linear (use-once) runtime value."""
    def __init__(self, value, linear=False):
        self.value    = value
        self.linear   = linear
        self.consumed = False

class Capability:
    def __init__(self, name): self.name = name
    def __repr__(self): return f"<Capability:{self.name}>"

class Effect:
    def __init__(self, name, func): self.name = name; self.func = func
    def __repr__(self): return f"<Effect:{self.name}>"

# ===========================================================================
# ENVIRONMENT
# ===========================================================================

class Environment(dict):
    """
    A lexical scope frame.  Each frame has an optional parent, forming a chain.
    Symbols are resolved by walking up the chain.
    """
    def __init__(self, initial_data=None, parent=None):
        super().__init__(initial_data or {})
        self.parent         = parent
        self.fixed          = set()     # immutable bindings
        self.sealed         = False     # locked namespace
        self.capabilities   = set()
        self.opened_modules = []

    # ── lookup ────────────────────────────────────────────────────────────

    def find(self, key: str) -> "Environment":
        """Return the frame that owns `key`, or raise NameError."""
        env = self
        while env is not None:
            if key in env: return env
            env = env.parent
        # try opened modules
        env = self
        visited = set()
        while env is not None:
            for mod in env.opened_modules:
                if id(mod) in visited: continue
                visited.add(id(mod))
                try: return mod.find(key)
                except NameError: pass
            env = env.parent
        raise NameError(f"Unbound symbol: {key}")

    def find_root(self) -> "Environment":
        env = self
        while env.parent is not None: env = env.parent
        return env

    def get_resource(self, key):
        frame = self.find(key)
        v = frame[key]
        if isinstance(v, Resource):
            if v.linear:
                if v.consumed: raise NameError(f"Linear Violation: '{key}' already consumed.")
                v.consumed = True
            return v.value
        return v

    # ── mutation ──────────────────────────────────────────────────────────

    def define(self, key, value, is_fixed=False):
        key = str(key)
        if self.sealed:
            raise NameError("Soundness Violation: cannot modify a sealed namespace.")
        if self.is_fixed_anywhere(key):
            raise NameError(f"Soundness Violation: cannot redefine fixed symbol '{key}'.")
        self[key] = value
        if is_fixed: self.fixed.add(key)

    def mutate(self, key, value):
        """set! — walk the chain to update an existing binding.
        NOTE: use 'is not None' not truthiness — an empty Environment is falsy."""
        if key in self:
            if key in self.fixed: raise NameError(f"Cannot mutate fixed symbol: {key}")
            self[key] = value
        elif self.parent is not None:
            self.parent.mutate(key, value)
        else:
            raise NameError(f"Cannot set! undefined symbol: {key}")

    def undefine(self, key):
        if key in self:
            if key in self.fixed: raise NameError(f"Cannot undefine fixed symbol: {key}")
            del self[key]; return True
        elif self.parent is not None: return self.parent.undefine(key)
        else: raise NameError(f"Cannot undefine undefined symbol: {key}")

    def bulk_define(self, mapping):
        for k, v in mapping.items(): self.define(k, v)

    def is_fixed_anywhere(self, key):
        if key in self.fixed: return True
        return self.parent.is_fixed_anywhere(key) if self.parent else False

    # ── capabilities ──────────────────────────────────────────────────────

    def grant(self, cap_name):   self.capabilities.add(cap_name)
    def revoke(self, cap_name):
        if cap_name in self.capabilities: self.capabilities.remove(cap_name)
        else: raise NameError(f"Capability '{cap_name}' not found.")
    def has_capability(self, name):
        return name in self.capabilities or (self.parent.has_capability(name) if self.parent else False)

    # ── serialization ────────────────────────────────────────────────────

    def serialize(self) -> str:
        """
        Flatten the full env chain (child wins over parent) into a JSON image.
        Saves: booleans, numbers, strings, lists, Lambdas, Macros, and
               user-registered reader macros from READ_TABLE.
        Skips: Python callables (primitives are re-created on boot).
        """
        out: dict = {}
        curr = self
        while curr is not None:
            for k, v in curr.items():
                if k in out: continue          # child already defined it
                s = _serialize_value(v)
                if s is not _UNSERIALIZABLE:
                    out[k] = s
            curr = curr.parent

        # Snapshot user-registered reader macros
        rm: dict = {}
        for char, fn in READ_TABLE.items():
            lh = getattr(fn, "lisp_handler", None)
            if lh is not None:
                rm[char] = _serialize_value(lh)
        out["__reader_macros__"] = rm

        return json.dumps(out, indent=2, sort_keys=True)


_UNSERIALIZABLE = object()   # sentinel for values we cannot persist

# ===========================================================================
# MODULE
# ===========================================================================

class Module:
    """
    A first-class module value returned by (import ...).

    Wraps an Environment with identity metadata so the evaluator never
    exposes raw Environment dicts to user code.  This is the stable
    abstraction boundary between the module system and the IR.

    Fields:
        name    — the canonical name used to import it ("sys", "mylib.ol")
        env     — the Environment holding the module's bindings
        origin  — "native" | "file" | "repl"
        exports — optional explicit export list (None = all public bindings)

    Design invariants:
      - Module is NOT a subclass of dict; it cannot be accidentally iterated
        as a raw binding bag
      - Attribute access: (getattr mod sym) looks up sym in mod.env
      - open: (open mod) copies mod.exports into the calling environment
      - repr: shows name + origin + export count, not raw bindings
    """
    def __init__(self, name: str, env: "Environment",
                 origin: str = "file", exports=None):
        self.name    = name
        self.env     = env
        self.origin  = origin    # "native" | "file" | "repl"
        self.exports = exports   # None → all public keys; list → explicit

    def public_keys(self):
        """Return the names this module exports."""
        if self.exports is not None:
            return [k for k in self.exports if k in self.env]
        # Default: everything not starting with _ and not internal sentinels
        return [k for k in self.env.keys()
                if not k.startswith("_") and k not in ("__reader_macros__",)]

    def lookup(self, key: str):
        """Look up a name in this module's environment."""
        return self.env.find(key)[key]

    def __repr__(self):
        keys = self.public_keys()
        preview = ", ".join(keys[:5])
        if len(keys) > 5: preview += f", … ({len(keys)} total)"
        return f"<Module '{self.name}' [{self.origin}] {{{preview}}}>"

    def __eq__(self, other):
        return isinstance(other, Module) and self.env is other.env

    def __hash__(self):
        return id(self.env)


def _serialize_value(v):
    """
    Convert a live value to a JSON-safe form.

    Conventions:
      None          → JSON null
      bool          → JSON bool  (must precede int check!)
      int/float     → JSON number
      str (literal) → JSON string wrapped in extra quotes: '"hello"'
                      (so hydration knows to strip them and return a str)
      Symbol        → JSON string without wrapping: "symbol-name"
                      (hydration restores as Symbol)
      list          → JSON array  (each element recursively serialized)
      Lambda        → {"__type__": "lambda", ...}
      Macro         → {"__type__": "macro",  ...}
      Environment   → {"__type__": "module", ...}
      callable/etc  → _UNSERIALIZABLE  (skipped from images)
    """
    if v is None:              return None
    if isinstance(v, bool):    return v        # bool before int!
    if isinstance(v, (int, float)): return v
    if isinstance(v, Symbol):  return str(v)   # symbol name — no extra quotes
    if isinstance(v, StringLiteral):
        # Store with wrapping quotes so hydration restores as StringLiteral
        # Escape any double-quotes in the content
        escaped = str(v).replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, str):
        # Plain str: sentinel or legacy quoted string.
        # If already wrapped in outer quotes, keep as-is; otherwise wrap.
        if v.startswith('"') and v.endswith('"'):
            return v
        return f'"{v}"'
    if isinstance(v, list):
        result = [_serialize_value(x) for x in v]
        # If any element is unserializable propagate the sentinel up
        return result  # partial serialization is OK for lists
    if isinstance(v, Lambda):
        result = {"__type__": "lambda",
                  "params":   [str(p) for p in v.params],
                  "body":     _serialize_value(v.body),
                  "effects":  [str(e) for e in getattr(v, "required_effects", [])]}
        if getattr(v, 'name',   None) is not None: result["name"]   = v.name
        if getattr(v, 'source', None) is not None: result["source"] = _serialize_value(v.source)
        return result
    if isinstance(v, Macro):
        return {"__type__": "macro",
                "params":   [str(p) for p in v.params],
                "body":     _serialize_value(v.body)}
    if isinstance(v, Module):
        data = {}
        for k, val in v.env.items():
            s = _serialize_value(val)
            if s is not _UNSERIALIZABLE:
                data[k] = s
        return {"__type__": "module", "name": v.name,
                "origin": v.origin, "data": data,
                "exports": v.exports}
    if isinstance(v, Environment):
        data = {}
        for k, val in v.items():
            s = _serialize_value(val)
            if s is not _UNSERIALIZABLE:
                data[k] = s
        return {"__type__": "module", "data": data}
    return _UNSERIALIZABLE   # callables, Capabilities, Effects, etc.

def _hydrate_value(v, root_env: Environment):
    """
    Reconstruct a live value from its serialized (JSON) form.

    JSON types map as follows:
      null        → None  (Python None, the empty/missing sentinel)
      bool        → bool
      number      → int / float
      string      → Symbol  (symbol names live in AST as Symbol objects;
                             quoted string literals are stored with wrapping
                             double-quotes in the JSON, e.g. '"hello"')
      list        → list  (each element recursively hydrated)
      {__type__:} → Lambda / Macro / Environment module
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        # Outer double-quotes → was a StringLiteral; strip them and restore content
        if v.startswith('"') and v.endswith('"') and len(v) >= 2:
            inner = v[1:-1]
            inner = inner.replace('\\"', '"').replace('\\\\', '\\')
            return StringLiteral(inner)
        # Everything else is a symbol name in an AST — restore as Symbol
        return Symbol(v)
    if isinstance(v, list):
        return [_hydrate_value(x, root_env) for x in v]
    if isinstance(v, dict):
        t = v.get("__type__")
        if t == "lambda":
            lam = Lambda(
                [Symbol(p) if isinstance(p, str) else p for p in v["params"]],
                _hydrate_value(v["body"], root_env),
                root_env,
                v.get("effects", [])
            )
            if "name"   in v: lam.name   = v["name"]
            if "source" in v: lam.source = _hydrate_value(v["source"], root_env)
            return lam
        if t == "macro":
            return Macro(
                [Symbol(p) if isinstance(p, str) else p for p in v["params"]],
                _hydrate_value(v["body"], root_env),
                root_env
            )
        if t == "module":
            mod_env = Environment(parent=root_env)
            for mk, mv in v.get("data", {}).items():
                mod_env.define(mk, _hydrate_value(mv, root_env))
            return Module(
                name    = v.get("name", "<restored>"),
                env     = mod_env,
                origin  = v.get("origin", "file"),
                exports = v.get("exports")
            )
        # Unknown dict — return as-is (data value)
        return v
    return v


# ===========================================================================
# PERSISTENCE
# ===========================================================================

def save_image(name: str, env_obj: Environment) -> str:
    """Serialize env to a content-addressed file in the store."""
    if not isinstance(env_obj, Environment):
        raise TypeError("Can only save an Environment object.")
    data_str     = env_obj.serialize()
    content_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]
    full_name    = f"{content_hash}-{name}"
    path         = os.path.join(get_store_path(), full_name)
    os.makedirs(get_store_path(), exist_ok=True)
    with open(path, "w") as f: f.write(data_str)
    return full_name

def load_prelude(env: Environment) -> None:
    """On startup, load the prelude image named in config (if enabled)."""
    cfg = _load_json_safe(get_config_path())
    target = cfg.get("prelude_file")
    if not cfg.get("prelude_enabled") or not target: return
    path = os.path.join(get_store_path(), target)
    if not os.path.exists(path):
        print(f"  ! Warning: Prelude file '{target}' not found in store.")
        return
    try:
        with open(path) as f: data = json.load(f)
    except Exception as e:
        print(f"  ! Warning: Failed to parse prelude '{target}': {e}"); return
    # Use env (the repl env) as the closure environment for hydrated Lambdas and
    # Macros so they can see each other when they recurse.  We first define all
    # keys with placeholder None, then hydrate — this way mutual recursion works.
    for k, v in data.items():
        if k == "__reader_macros__": continue
        try:
            env.define(k, None)
        except NameError:
            pass  # already defined (fixed primitive) — skip
    for k, v in data.items():
        if k == "__reader_macros__":
            for char, spec in v.items():
                handler = _hydrate_value(spec, env)
                register_reader_macro(char, handler)
            continue
        hydrated = _hydrate_value(v, env)
        try:
            env.mutate(k, hydrated)
        except NameError:
            try:
                env.define(k, hydrated)
            except NameError:
                pass  # fixed primitive — skip
    print(f"  [System] Prelude loaded from: {target}")

def load_image(name: str, target_env: Environment) -> Environment:
    """Load a saved image into a new module env hanging off target_env's root."""
    path = os.path.join(get_store_path(), name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image '{name}' not found in store.")
    with open(path) as f:
        data = json.load(f)
    new_mod = Environment(parent=target_env.find_root())
    # Two-pass: define placeholders first, then hydrate, so mutual recursion works
    for k, v in data.items():
        if k == "__reader_macros__": continue
        try: new_mod.define(k, None)
        except NameError: pass
    for k, v in data.items():
        if k == "__reader_macros__":
            for char, spec in v.items():
                handler = _hydrate_value(spec, new_mod)
                register_reader_macro(char, handler)
            continue
        hydrated = _hydrate_value(v, new_mod)
        try:
            new_mod.mutate(k, hydrated)
        except NameError:
            try: new_mod.define(k, hydrated)
            except NameError: pass
    return new_mod

def auto_save(env: Environment) -> None:
    """Save the session on exit and update the prelude pointer."""
    try:
        name = save_image("autosave", env)
        save_config({"prelude_file": name, "prelude_enabled": True})
        print(f"  [System] Session saved as: {name}")
    except Exception as e:
        print(f"  [System] Auto-save failed: {e}")


# ===========================================================================
# READER / TOKENIZER
# ===========================================================================

READ_TABLE: dict = {}      # char → callable(stream) → AST node

class Stream:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos    = 0
    def next(self):
        if self.pos >= len(self.tokens): return None
        t = self.tokens[self.pos]; self.pos += 1; return t
    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None
    def clear(self):
        self.pos = len(self.tokens)

def tokenize(s: str) -> list:
    """
    Break source text into tokens.

    - Semicolon comments (`;` to end of line) are stripped, respecting strings.
    - Escaped quotes inside strings (`\"`) are handled correctly.
    - Bracket annotations like [cite: ...] are NOT stripped here —
      they are handled by the `[` reader macro dispatch (SKIP_SIGNAL).
    - Dispatch characters  ' ` , ,@  and brackets [ ]
      always become standalone tokens.
    - Double-quoted strings (including escape sequences) are single tokens.
    """
    clean_lines = []
    for line in s.splitlines():
        in_str = False
        escaped = False
        out = []
        for ch in line:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == '\\' and in_str:
                out.append(ch)
                escaped = True
            elif ch == '"':
                in_str = not in_str
                out.append(ch)
            elif ch == ';' and not in_str:
                break          # rest of line is a comment
            else:
                out.append(ch)
        clean_lines.append("".join(out))
    cleaned = "\n".join(clean_lines)
    # Strings with escape sequences, then structural chars, then atoms.
    # [ and ] are standalone tokens so the bracket reader macro can dispatch on them.
    pattern = r'("(?:\\.|[^"\\])*"|\(|\)|\[|\]|,@|[\'`,]|[^\s()\[\]"\'`,]+)'
    return re.findall(pattern, cleaned)

def atom(token: str):
    try: return int(token)
    except ValueError: pass
    try: return float(token)
    except ValueError: pass
    if token.startswith('"') and token.endswith('"'):
        # Unescape the content and wrap in StringLiteral — unambiguous at all times
        inner = token[1:-1]
        inner = inner.replace('\\\\', '\x00BS\x00')
        inner = inner.replace('\\"',  '"')
        inner = inner.replace('\\n',  '\n')
        inner = inner.replace('\\t',  '\t')
        inner = inner.replace('\\r',  '\r')
        inner = inner.replace('\x00BS\x00', '\\')
        return StringLiteral(inner)
    return Symbol(token)

def read_node(stream: Stream):
    token = stream.next()
    if token is None: return None
    if isinstance(token, list): return token
    if token in READ_TABLE:
        result = READ_TABLE[token](stream)
        return read_node(stream) if result is SKIP_SIGNAL else result
    if token == "(":
        L = []
        while stream.peek() != ")" and stream.peek() is not None:
            L.append(read_node(stream))
        stream.next()   # consume ')'
        return L
    if token == ")":
        raise SyntaxError("Unexpected )")
    return atom(token)

def _semicolon_reader(stream):
    while stream.next() is not None: pass
    return SKIP_SIGNAL

def _bracket_reader(stream):
    """Skip a [bracket annotation] like [cite:...] silently.
    [ and ] are standalone tokens; consume until the matching ]."""
    depth = 1
    while depth > 0:
        t = stream.next()
        if t is None: break
        if t == "[": depth += 1
        elif t == "]": depth -= 1
    return SKIP_SIGNAL

# Built-in dispatch characters
READ_TABLE[";"]  = _semicolon_reader
READ_TABLE["["]  = _bracket_reader    # silently skip [cite:...] annotations
READ_TABLE["'"]  = lambda s: ["quote",            read_node(s)]
READ_TABLE["`"]  = lambda s: ["quasiquote",        read_node(s)]
READ_TABLE[",@"] = lambda s: ["unquote-splicing",  read_node(s)]
READ_TABLE[","]  = lambda s: ["unquote",           read_node(s)]

def register_reader_macro(char: str, func) -> str:
    """
    Register a Lisp Lambda (or Macro) as a reader dispatch function for `char`.

    The function is called with the Stream positioned *after* the dispatch char
    and must return an AST node.  The .lisp_handler attribute lets serialize()
    snapshot it so the macro survives save/load.

    Example:
        (register-reader-macro! '~
          (lambda (stream)
            (list 'inc (read stream))))
        ~ 5  =>  (inc 5)  =>  6
    """
    def wrapper(stream):
        if isinstance(func, Macro):
            menv = Environment(parent=func.env)
            if func.params: menv.define(str(func.params[0]), stream)
            res = eval_node(func.body, menv, set())
        else:
            res = apply(func, [stream], func.env, set())
        while isinstance(res, TailCall):
            res = eval_node(res.expr, res.env, set())
        return res
    wrapper.lisp_handler = func
    READ_TABLE[str(char)] = wrapper
    return f"Registered reader macro for '{char}'"

def reset_reader_macros() -> None:
    """Remove only user-registered reader macros (preserves built-ins)."""
    for k in list(READ_TABLE.keys()):
        if hasattr(READ_TABLE[k], "lisp_handler"):
            del READ_TABLE[k]


# ===========================================================================
# QUASIQUOTE
# ===========================================================================

def quasiquote_expand(expr) -> list:
    """
    Lower a quasiquoted form into ordinary list-construction AST.
      `atom       →  (quote atom)
      `(a ,b ,@c) →  (append (list (quote a)) (list b) c)
    """
    if not isinstance(expr, list):
        return [Symbol("quote"), expr]
    if len(expr) == 2 and expr[0] == "unquote":
        return expr[1]
    parts = []
    for item in expr:
        if isinstance(item, list) and len(item) == 2 and item[0] == "unquote-splicing":
            parts.append(item[1])
        else:
            parts.append([Symbol("list"), quasiquote_expand(item)])
    result = [Symbol("quote"), []]
    for part in parts:
        result = [Symbol("append"), result, part]
    return result


# ===========================================================================
# APPLY  (Lambda, Effect, callable — in that priority order)
# ===========================================================================

def _structural_key(args):
    """
    Convert a list of arguments into a hashable cache key.
    Handles lists, nested lists, and primitive values.
    Falls back to id() for anything else (Python objects, Lambdas).
    """
    def to_key(v):
        if isinstance(v, list):
            return ("__list__",) + tuple(to_key(x) for x in v)
        if isinstance(v, (int, float, str, bool, type(None))):
            return v
        return ("__id__", id(v))
    return tuple(to_key(a) for a in args)


def _structural_equal(a, b) -> bool:
    """
    Deep structural equality — the semantics of equal? / = for non-numbers.
    Recursively compares lists element-by-element.
    For atoms uses Python == (so symbols compare by name, numbers by value).
    """
    if type(a) != type(b):
        # Allow int/float comparison
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_structural_equal(x, y) for x, y in zip(a, b))
    return a == b


def _make_memoized_wrapper(f, env):
    """
    Build a memoized wrapper around f.  Uses _structural_key so list
    arguments (and nested structures) are cached correctly.
    """
    cache = {}
    def memoized(*args):
        k = _structural_key(args)
        if k not in cache:
            result = apply(f, list(args), env, set())
            while isinstance(result, TailCall):
                result = eval_node(result.expr, result.env, set())
            cache[k] = result
        return cache[k]
    memoized._memo        = cache
    memoized._original    = f
    memoized._is_memoized = True
    return memoized


_TRACE_DEPTH = [0]   # mutable counter for indentation

def _make_traced_wrapper(f):
    """
    Wrap f so every call prints its arguments and return value.
    Output is indented by call depth so nested calls are readable.
    """
    name = getattr(f, 'name', None) or getattr(f, '__name__', '?')
    def traced(*args):
        indent = "  " * _TRACE_DEPTH[0]
        arg_str = " ".join(repr(a) for a in args)
        print(f"{indent}→ ({name} {arg_str})")
        _TRACE_DEPTH[0] += 1
        try:
            # Use apply for Lambda objects so the trampoline handles tail calls
            result = apply(f, list(args), None, set())
            while isinstance(result, TailCall):
                result = eval_node(result.expr, result.env, set())
        finally:
            _TRACE_DEPTH[0] -= 1
        print(f"{indent}← {name} = {result!r}")
        return result
    traced._original  = f
    traced._is_traced = True
    return traced


def apply(func, args, calling_env, _visited=None):
    if isinstance(func, Effect):
        if calling_env and not calling_env.has_capability(func.name):
            raise PermissionError(f"Effect Violation: missing '{func.name}' capability.")
        return apply(func.func, args, calling_env, _visited)

    if isinstance(func, Lambda):
        for eff in func.required_effects:
            if calling_env and not calling_env.has_capability(eff):
                raise PermissionError(f"Soundness Violation: missing '{eff}' capability.")
        new_env = Environment(parent=func.env)
        new_env.opened_modules = list(func.env.opened_modules)
        params = func.params
        if not isinstance(params, list):
            new_env[str(params)] = list(args)
        elif '.' in [str(p) for p in params]:
            dot_idx = next(i for i,p in enumerate(params) if str(p)=='.')
            fixed = params[:dot_idx]
            rest_p = str(params[dot_idx+1]) if dot_idx+1<len(params) else None
            for n,v in zip(fixed, args): new_env[str(n)] = v
            if rest_p: new_env[rest_p] = list(args[len(fixed):])
        else:
            for name, value in zip(params, args):
                new_env[str(name)] = value
        return TailCall(func.body, new_env)

    if callable(func):
        return func(*args)

    raise TypeError(f"Not a function: {func!r}")


# ===========================================================================
# MACRO EXPANSION  (for the (expand ...) special form)
# ===========================================================================

def macro_expand(macro: Macro, args: list, env: Environment):
    """Expand a macro call: bind raw AST args to params, eval body → new AST.

    The body is evaluated in menv (an env where params are bound to raw arg ASTs).
    This correctly handles all body styles:
      - (quote ...)      body: eval returns the quoted list as the new AST
      - (quasiquote ...) body: eval resolves ,unquotes → new AST
      - (list ...)       body: eval calls list() → new AST list
      - any expression   body: eval produces the new AST

    The returned value is the expanded AST, which the caller trampolines in the
    calling env. This means symbols in the expanded form (like Symbol('x')) are
    resolved in the calling env, not the macro env — correct non-hygienic behavior.

    Hygiene note: if a macro param name (e.g. 'x') collides with a variable name
    in the calling scope, the substitution inserts Symbol('x') into the expanded
    form, which then looks up 'x' in the calling env. This is intentional
    non-hygienic behavior. Use gensym to avoid collisions when needed.
    """
    menv = Environment(parent=macro.env)
    params = macro.params
    # Handle variadic dotted-pair params: (a b . rest) stored as ['a', 'b', '.', 'rest']
    if isinstance(params, list) and '.' in [str(p) for p in params]:
        dot_idx      = next(i for i, p in enumerate(params) if str(p) == '.')
        fixed_params = params[:dot_idx]
        rest_param   = params[dot_idx + 1] if dot_idx + 1 < len(params) else None
        for param, arg in zip(fixed_params, args):
            menv.define(str(param), arg)
        if rest_param is not None:
            menv.define(str(rest_param), list(args[len(fixed_params):]))
    else:
        for param, arg in zip(params, args):
            menv.define(str(param), arg)
    return eval_node(macro.body, menv, set())

def macro_substitute(macro: Macro, args: list) -> object:
    """
    Pure syntactic substitution for (expand ...).
    Evaluates the macro body to get the template (handles quasiquote etc.),
    then walks the result and replaces any param-name symbols with the
    corresponding raw arg values.  Does NOT evaluate the final form.
    """
    # Build the substitution map: param-name → raw arg AST
    subs = {str(p): a for p, a in zip(macro.params, args)}
    def subst(node):
        if isinstance(node, (str, Symbol)) and str(node) in subs:
            return subs[str(node)]
        if isinstance(node, list):
            return [subst(x) for x in node]
        return node
    # Get the template by evaluating the body in an env where params are bound
    menv = Environment(parent=macro.env)
    for param, arg in zip(macro.params, args):
        menv.define(str(param), arg)
    return eval_node(macro.body, menv, set())

def expand_all(expr, env, _visited=None, substitute_only=False):
    """Recursively expand all macro calls in an AST without evaluating.
    substitute_only=True is used by (expand ...) to show the raw expanded form."""
    if not isinstance(expr, list): return expr
    head = expr[0]
    head_val = None
    if isinstance(head, (str, Symbol)):
        try: head_val = env.find_root().find(str(head))[str(head)]
        except NameError: pass
    if isinstance(head_val, Macro):
        expanded = macro_expand(head_val, expr[1:], head_val.env)
        return expand_all(expanded, env, _visited)
    return [expand_all(e, env, _visited) for e in expr]


# ===========================================================================
# TRAMPOLINE  (TCO loop)
# ===========================================================================


def is_lisp_true(val):
    """Only the Python False object is false in Lisp."""
    if val is False: return False
    return True

def trampoline(node, env):
    result = eval_node(node, env, set())
    while isinstance(result, TailCall):
        result = eval_node(result.expr, result.env, set())
    return result


# ===========================================================================
# PRIMITIVES
# ===========================================================================



def _raise(exc: Exception):
    raise exc

def _escape_newlines_in_py_strings(s: str) -> str:
    """
    Escape literal newlines that appear inside Python double-quoted string
    literals within `s`.  This makes generated Python source safe to write
    as a single-line expression.

    State machine: walk `s` char by char, tracking whether we are inside
    a double-quoted string literal.  When we find a real newline inside
    a string, replace it with the two-char sequence \\n.
    """
    out = []
    in_str = False
    escaped = False
    i = 0
    while i < len(s):
        ch = s[i]
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == '\\' and in_str:
            out.append(ch)
            escaped = True
        elif ch == '"':
            in_str = not in_str
            out.append(ch)
        elif ch == '\n' and in_str:
            out.append('\\')   # replace real newline with \n escape sequence
            out.append('n')
        else:
            out.append(ch)
        i += 1
    return "".join(out)

# Persistent namespace shared by py-eval and py-exec.
# This lets (py-exec "import foo") make 'foo' visible to later (py-eval "foo.bar()")
_py_exec_globals: dict = {"__builtins__": __builtins__}


def _py_resolve_path(path: str):
    """
    Resolve a dotted Python path like "tkinter.Label" or "math.sqrt"
    using _py_exec_globals (honoring py-exec imports) and importlib as fallback.
    """
    parts = path.split(".")
    # First part: try _py_exec_globals, then importlib
    if parts[0] in _py_exec_globals:
        obj = _py_exec_globals[parts[0]]
    else:
        try:
            import importlib as _il
            obj = _il.import_module(parts[0])
        except ImportError:
            raise NameError(f"py-call: cannot resolve '{parts[0]}'")
    for part in parts[1:]:
        obj = getattr(obj, part)
    return obj


def _py_unwrap(val):
    """
    Convert an Omega value to a plain Python value for passing to native APIs.
    Omega Lambdas become zero-argument Python callables (for tkinter callbacks).
    """
    if isinstance(val, Lambda):
        return _py_make_callback(val)
    return val


def _py_make_callback(f):
    """
    Wrap an Omega Lambda (or memoized wrapper) as a Python callable.
    tkinter callbacks are called with zero args.
    Keeps a strong reference to f to prevent garbage collection.
    """
    # Keep strong reference so GC doesn't collect the lambda
    _f_ref = f
    def callback(*_args):
        try:
            _apply = globals()["apply"]
            _eval  = globals()["eval_node"]
            _TC    = globals()["TailCall"]
            _env   = globals().get("env")   # REPL env for calling context
            result = _apply(_f_ref, [], _env, set())
            while isinstance(result, _TC):
                result = _eval(result.expr, result.env, set())
        except Exception as e:
            print(f"  ! Callback error: {e}")
    # Name the function for easier debugging
    if hasattr(f, 'name'):
        callback.__name__ = f"omega_cb_{f.name}"
    return callback


def _py_parse_kwargs(args):
    """
    Parse a flat list of args where keyword args are :key value pairs.
    Returns (positional_list, kwargs_dict).
    """
    positional = []
    kwargs = {}
    i = 0
    while i < len(args):
        a = args[i]
        if isinstance(a, Symbol) and str(a).startswith(":"):
            key = str(a)[1:]  # strip leading :
            val = _py_unwrap(args[i + 1]) if i + 1 < len(args) else None
            kwargs[key] = val
            i += 2
        else:
            positional.append(_py_unwrap(a))
            i += 1
    return positional, kwargs


def _py_call_kw(path: str, args):
    """(py-call-kw "tkinter.Button" root :text "Hi" :command cb)"""
    fn = _py_resolve_path(path)
    positional, kwargs = _py_parse_kwargs(args)
    return fn(*positional, **kwargs)


def _py_call_method_kw(obj, method: str, args):
    """(py-call-method-kw widget "config" :text "new")"""
    fn = getattr(obj, method)
    positional, kwargs = _py_parse_kwargs(args)
    return fn(*positional, **kwargs)

# ===========================================================================
# MODULE RESOLVER
# ===========================================================================
#
# The ModuleResolver sits between the `import` special form and the filesystem.
# It decides HOW a module name is resolved without changing any other evaluator
# semantics — the result is always a plain value or Environment bound into env,
# exactly as before.
#
# Resolution tiers (checked in order):
#   1. Native host module  — a Python stdlib or third-party module name
#                            (sys, re, os, math, json, ...)
#   2. File module         — a .ol Lisp source file (existing behaviour)
#   3. Alias               — a dot-separated stdlib submodule (os.path, ...)
#
# Adding support for a new source language requires ONLY adding its stdlib
# names to NATIVE_MODULES (or calling resolver.register()).  Nothing else
# in the evaluator changes.

import importlib as _importlib

class ModuleResolver:
    """
    Resolve an import name to either a Python (native) object or a Lisp
    file-module path.

    Usage inside eval_node:
        kind, value = _module_resolver.resolve(name)
        if kind == "native":
            env.define(alias, value)      # value is the Python module object
        elif kind == "file":
            <existing file-loading logic>(value)  # value is the resolved path

    Languages are registered as sets of known stdlib module names.  When a
    name appears in ANY registered language's stdlib set it resolves as native.
    """

    # Known Python standard-library top-level module names.
    # Extend this list as needed; it does NOT need to be exhaustive —
    # any name not listed here falls through to file resolution as before.
    _PYTHON_STDLIB = {
        # built-ins / core
        "sys", "os", "re", "math", "json", "hashlib", "shutil",
        "traceback", "functools", "itertools", "operator", "copy",
        "collections", "io", "abc", "types", "typing",
        # filesystem / paths
        "pathlib", "glob", "fnmatch", "tempfile", "stat",
        # string / text
        "string", "textwrap", "unicodedata", "codecs",
        # time
        "time", "datetime", "calendar",
        # data
        "struct", "array", "heapq", "bisect", "queue",
        # concurrency
        "threading", "multiprocessing", "subprocess", "signal",
        # networking
        "socket", "ssl", "http", "urllib", "email", "html",
        # misc stdlib
        "random", "statistics", "decimal", "fractions",
        "contextlib", "dataclasses", "enum", "weakref",
        "inspect", "dis", "ast", "tokenize", "importlib",
        "unittest", "logging", "warnings", "pprint",
        "platform", "uuid", "base64", "binascii", "csv",
        "sqlite3", "pickle", "shelve", "configparser",
        "argparse", "getopt", "getpass",
        # common third-party (pre-cached if installed)
        "numpy", "pandas", "scipy", "matplotlib",
        "requests", "flask", "django", "fastapi",
        "pytest", "hypothesis",
        "prompt_toolkit",
    }

    def __init__(self):
        # Maps language tag → set of known stdlib names for that language
        self._registries: dict = {"python": self._PYTHON_STDLIB}

    def register(self, language: str, module_names):
        """Add module names for a new source language."""
        s = self._registries.setdefault(language, set())
        s.update(module_names)

    def is_native(self, name: str) -> bool:
        """True if `name` is a known host-language module name."""
        # Check top-level name (handles "os.path" → "os")
        root = name.split(".")[0]
        return any(root in reg for reg in self._registries.values())

    def resolve_native(self, name: str):
        """
        Import and return a Python module object.
        Supports dotted names: "os.path" returns the os.path submodule.
        """
        try:
            mod = _importlib.import_module(name)
            return mod
        except ImportError:
            # Try as attribute access: "os.path" → getattr(os, "path")
            parts = name.split(".")
            try:
                mod = _importlib.import_module(parts[0])
                for part in parts[1:]:
                    mod = getattr(mod, part)
                return mod
            except (ImportError, AttributeError):
                return None

    def resolve(self, name: str, search_paths=None):
        """
        Resolve `name` to (kind, value):
          ("native", <python-module>)   — host module, no filesystem access
          ("file",   <path-string>)     — Lisp source file path
          ("unknown", name)             — neither; caller decides how to error
        """
        if self.is_native(name):
            mod = self.resolve_native(name)
            if mod is not None:
                return ("native", mod)
            # native name but import failed — fall through to file
        # File resolution: try the name as given, then with .ol extension
        candidates = [name]
        if not name.endswith(".ol") and not os.path.splitext(name)[1]:
            candidates.append(name + ".ol")
        for path in candidates:
            if os.path.exists(path):
                return ("file", path)
        return ("unknown", name)


# The single global resolver instance — shared across all eval_node calls.
_module_resolver = ModuleResolver()

def _make_primitives(current_env: Environment) -> dict:

    # Higher-order helpers that trampoline Lambda calls correctly
    def call(f, args):
        r = apply(f, list(args), current_env)
        while isinstance(r, TailCall):
            r = eval_node(r.expr, r.env, set())
        return r

    def lisp_map(f, lst):     return [call(f, [x]) for x in lst]
    def lisp_filter(f, lst):  return [x for x in lst if call(f, [x])]
    def lisp_for_each(f, lst):
        for x in lst: call(f, [x])
        return None

    def lisp_reduce(f, lst, *init):
        if not isinstance(lst, list):
            raise TypeError(f"reduce: expected a list, but got {type(lst).__name__} ({lst})")
        acc = init[0] if init else lst[0]
        seq = lst if init else lst[1:]
        for x in seq: acc = call(f, [acc, x])
        return acc

    def lisp_fold(f, init, lst):
        # Scheme/SRFI-1 argument order: (fold f init lst)
        if not isinstance(lst, list):
            raise TypeError(f"fold: expected a list, but got {type(lst).__name__} ({lst})")
        acc = init
        for x in lst: acc = call(f, [acc, x])
        return acc

    def lisp_memoize(f):
        """
        (memoize f) → new function that caches results by structural key.
        Uses _structural_key so list arguments cache correctly.
        Works for any Omega Lambda or Python callable.
        """
        cache = {}
        def memoized(*args):
            key = _structural_key(args)
            if key not in cache:
                cache[key] = call(f, list(args))
            return cache[key]
        memoized._memo        = cache
        memoized._original    = f
        memoized._is_memoized = True
        return memoized

    def lisp_memoize_inplace(name_sym, calling_env):
        """
        (memoize! 'fname) — replace the named binding with a memoized version.
        Because the function calls itself by name, we need the cache to be in
        place before the first recursive call — otherwise only the top call
        is cached.  We achieve this by:
          1. Look up the current Lambda by name.
          2. Build a memoized wrapper.
          3. Rebind the name to the wrapper IN the env where it lives.
        This means recursive calls (which look up the name at each step) will
        hit the cache on subsequent visits.
        """
        key = str(name_sym)
        frame = calling_env.find(key)
        f = frame[key]
        if getattr(f, '_is_memoized', False):
            return f   # already memoized — idempotent
        cache = {}
        def memoized(*args):
            k = tuple(args)
            if k not in cache:
                cache[k] = call(f, list(args))
            return cache[k]
        memoized._memo        = cache
        memoized._original    = f
        memoized._is_memoized = True
        # Rebind in the frame that owns the name so recursive self-calls hit cache
        frame[key] = memoized
        return memoized

    def lisp_apply(f, lst): return call(f, list(lst))

    return {
        # --- Arithmetic ---------------------------------------------------
        "+":    lambda *a: sum(a),
        "-":    lambda x, *r: x - sum(r) if r else -x,
        "*":    lambda *a: py_reduce(lambda x,y: x*y, a, 1),
        "/":    lambda x, *r: py_reduce(lambda a,b: a/b, r, x),
        "mod":  lambda x, y: x % y,
        "**":   lambda x, y: x ** y,
        # --- Comparison ---------------------------------------------------
        "<":    lambda x, y: x < y,
        ">":    lambda x, y: x > y,
        "<=":   lambda x, y: x <= y,
        ">=":   lambda x, y: x >= y,
        "=":    lambda x, y: x == y,
        "not=": lambda x, y: x != y,
        # ── Equality ──────────────────────────────────────────────────────
        # eq?    — identity (same object in memory, like Python `is`)
        # equal? — structural deep equality (like Python ==, but list-aware)
        "eq?":    lambda x, y: x is y,
        "equal?": lambda x, y: _structural_equal(x, y),
        # --- Python interop (for lifted code) --------------------------------
        "getattr":    lambda obj, attr: getattr(obj, str(attr)),
        "get":        lambda obj, key: obj[key],
        "isinstance": lambda obj, typ: isinstance(obj, typ),
        "is":         lambda a, b: a is b,
        "is-not":     lambda a, b: a is not b,
        "in":         lambda a, b: a in b,
        "not-in":     lambda a, b: a not in b,
        "len":        len,
        "str":        str,
        "int":        int,
        "float":      float,
        "bool":       bool,
        "repr":       repr,
        "open":       open,
        "zip":        lambda *a: list(zip(*a)),
        "tuple":      lambda *a: tuple(a),
        "set":        lambda *a: set(a),
        "slice":      lambda *a: slice(*a),
        "dict":       lambda *pairs: dict(pairs),
        # --- Math ---------------------------------------------------------
        "sqrt": math.sqrt,  "abs":  abs,
        "floor":math.floor, "ceil": math.ceil,  "round": round,
        "max":  lambda *a: max(a), "min": lambda *a: min(a),
        # --- Logic --------------------------------------------------------
        "not":  lambda x: not x,
        # --- Lists --------------------------------------------------------
        "list":      lambda *a: list(a),
        "cons":      lambda x, lst: [x] + (lst if isinstance(lst, list) else [lst]),
        "prepend":   lambda x, lst: [x] + (lst if isinstance(lst, list) else [lst]),
        "append":    lambda *args: sum((list(a) for a in args), []),
        "first":  lambda x: x[0] if isinstance(x, (list, tuple)) and len(x) > 0 else None,
        "second": lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) > 1 else None,
        "third":  lambda x: x[2] if isinstance(x, (list, tuple)) and len(x) > 2 else None,
        "nth":    lambda lst, i: lst[int(i)] if isinstance(lst, (list, tuple)) and len(lst) > int(i) else None,
        "rest":      lambda x: x[1:] if x else [],
        "length":    lambda x: len(x),
        "reverse":   lambda x: list(reversed(x)),
        "null?":     lambda x: x is None or x == [],
        "pair?":     lambda x: isinstance(x, list) and len(x) > 0,
        "flatten":   lambda lst: sum((x if isinstance(x,list) else [x] for x in lst), []),
        "zip-lists": lambda a, b: [list(p) for p in zip(a, b)],
        "range":     lambda *a: list(range(*[int(x) for x in a])),
        "sort":      lambda lst: sorted(lst),
        "sort-by":   lambda f, lst: sorted(lst, key=lambda x: call(f, [x])),
        "map":       lisp_map,
        "filter":    lisp_filter,
        "reduce":    lisp_reduce,
        "fold":      lisp_fold,      # Scheme-order: (fold f init lst)
        "for-each":  lisp_for_each,
        "apply":     lisp_apply,
        # --- Type predicates ----------------------------------------------
        "number?":        lambda x: isinstance(x, (int,float)) and not isinstance(x,bool),
        "integer?":       lambda x: isinstance(x, int) and not isinstance(x,bool),
        # string? tests RUNTIME values: plain str that is not a Symbol.
        # StringLiteral is an AST-level type; once evaluated it becomes plain str.
        "string?":        lambda x: isinstance(x, str) and not isinstance(x, Symbol),
        "string-literal?":lambda x: isinstance(x, StringLiteral),  # AST-level only
        "symbol?":        lambda x: isinstance(x, Symbol),
        "list?":     lambda x: isinstance(x, list),
        "lambda?":   lambda x: isinstance(x, Lambda),
        "macro?":    lambda x: isinstance(x, Macro),
        "continuation?": lambda x: _is_continuation(x),
        "multi-shot!": _make_multi_shot,
        "bool?":     lambda x: isinstance(x, bool),
        "atom?":     lambda x: not isinstance(x, list),
        "env?":      lambda x: isinstance(x, Environment),
        # --- Strings / Symbols --------------------------------------------
        "symbol->string":  lambda s: str(s),
        "string->symbol":  lambda s: Symbol(s),
        "string-append":   lambda *args: "".join(str(a) for a in args), #lambda a, b: str(a) + str(b),
        "string->list":    lambda s: list(s),
        "list->string":    lambda lst: "".join(str(c) for c in lst),
        "string-length":   lambda s: len(s),
        "substring":       lambda s, a, b: s[int(a):int(b)],
        "string-upcase":   lambda s: s.upper(),
        "string-downcase": lambda s: s.lower(),
        "string-contains": lambda s, sub: sub in s,
        "string-split":    lambda s, sep: s.split(sep),
        "string->number":  lambda s: int(s) if str(s).lstrip("-").isdigit() else float(s),
        "number->string":  lambda n: str(n),
        "string-ref":      lambda s, i: s[int(i)],
        "int->char":       lambda i: chr(int(i)),
        "char->int":       lambda c: ord(c),
        # "string-replace":  lambda s, old, new: s.replace(old, new),
        # --- I/O ----------------------------------------------------------
        "print":   lambda *a: print(*a) or None,
        "display": lambda x: print(x, end="") or None,
        "newline": lambda: print() or None,
        "py-eval":    lambda code: eval(str(code), _py_exec_globals),
        "py-exec":    lambda code: (exec(str(code), _py_exec_globals), None)[1],
        # ── Python object interop ─────────────────────────────────────────
        # (py-call "module.ClassName" arg1 arg2)
        #   Instantiate a Python class or call a dotted function path.
        #   String args are resolved through _py_exec_globals (honours py-exec imports).
        # (py-call-method obj "method_name" arg1 arg2)
        #   Call a method on an existing Python object.
        # (py-get-attr obj "attr")   — read an attribute
        # (py-set-attr obj "attr" v) — write an attribute
        # (py-wrap-callback f)
        #   Wrap an Omega Lambda as a zero-argument Python callable suitable
        #   for passing to tkinter command= and similar callbacks.
        "py-call": lambda path, *args: (
            _py_resolve_path(str(path))(*[_py_unwrap(a) for a in args])
        ),
        "py-call-method": lambda obj, method, *args: (
            getattr(obj, str(method))(*[_py_unwrap(a) for a in args])
        ),
        "py-call-kw": lambda path, *args: _py_call_kw(str(path), args),
        "py-call-method-kw": lambda obj, method, *args: _py_call_method_kw(obj, str(method), args),
        "py-get-attr":  lambda obj, attr: getattr(obj, str(attr)),
        "py-set-attr":  lambda obj, attr, val: (setattr(obj, str(attr), _py_unwrap(val)), obj)[1],
        "py-isinstance": lambda obj, cls_path: isinstance(obj, _py_resolve_path(str(cls_path))),
        "py-wrap-callback": lambda f: _py_make_callback(f),
        "py-none?":     lambda x: x is None,
        "py-type":      lambda x: type(x).__name__,
        # Register additional native module names so (import "name") resolves
        # them as host modules rather than trying to load a .ol file.
        # Usage: (register-native-module! "js-stdlib" '("console" "window"))
        "register-native-module!": lambda lang, names: (
            _module_resolver.register(str(lang), [str(n) for n in names])
            or f"registered {len(names)} module(s) for '{lang}'"
        ),
        # Expose the resolver itself for inspection
        "native-module?": lambda name: _module_resolver.is_native(str(name)),
        # ── Module ABI ────────────────────────────────────────────────────
        # These primitives form the stable contract for working with Module
        # objects from any source language.  All cross-language code should
        # use these instead of direct attribute access.
        "module?":         lambda x: isinstance(x, Module),
        "module-name":     lambda m: m.name if isinstance(m, Module) else None,
        "module-origin":   lambda m: m.origin if isinstance(m, Module) else None,
        "module-exports":  lambda m: m.public_keys() if isinstance(m, Module) else [],
        "module-lookup":   lambda m, k: m.lookup(str(k)) if isinstance(m, Module) else None,
        # ── Memoization ───────────────────────────────────────────────────
        # (memoize f)      — wrap f in a new memoized function; f is unchanged
        # (memoize! 'name) — rebind name to its memoized version in-place
        #                    so recursive self-calls are also cached
        # (memo-clear! f)  — clear the cache on a memoized function
        # (memo-stats f)   — return cache hit count and size as [hits misses]
        "memoize":    lisp_memoize,
        "memo-clear!": lambda f: (f._memo.clear() or f) if hasattr(f, '_memo') else f,
        "memo-stats":  lambda f: (
            [len(f._memo), getattr(f, '_misses', 0)]
            if hasattr(f, '_memo') else None
        ),
        "memoized?":   lambda f: getattr(f, '_is_memoized', False),
        # ── Call tracing ──────────────────────────────────────────────────
        # (trace-calls f)   — wrap f to print each call and return value
        # (untrace-calls f) — unwrap back to original
        # (traced? f)       — predicate
        "trace-calls": lambda f: _make_traced_wrapper(f),
        "untrace-calls": lambda f: (
            getattr(f, '_original', f)
        ),
        "traced?":     lambda f: getattr(f, '_is_traced', False),
        "module-env":      lambda m: m.env if isinstance(m, Module) else None,
        # Set explicit exports on a module — (set-exports! mod '(foo bar))
        "set-exports!":    lambda m, ks: (
            setattr(m, 'exports', [str(k) for k in ks]) or m
            if isinstance(m, Module) else None
        ),
        # register-reader-macro! — ensure it accepts the char as a quoted symbol
        "register-reader-macro!": lambda char, func=None: (
            register_reader_macro(str(char), func) if func is not None
            else (lambda f: register_reader_macro(str(char), f))
        ),
        "write-file":          lambda path, content: (open(str(path), 'w').write(str(content)), str(path))[1],
        "read-file":           lambda path: open(str(path)).read(),
        "string-escape-nl":    lambda s: str(s).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"'),
        "escape-py-strings":   lambda s: _escape_newlines_in_py_strings(str(s)),
        # --- Misc ---------------------------------------------------------
        "begin":    lambda *a: a[-1] if a else None,
        "identity": lambda x: x,
        "error!":   lambda msg: _raise(Exception(str(msg))),
        "gensym":   lambda prefix="g": _gensym(prefix),
        "hash":     compute_hash,
        "type-of":  lambda x: type(x).__name__,
        "repr":     repr,
        # --- Environment / modules ----------------------------------------
        "current-env":    lambda: current_env,
        "find-root":      lambda: current_env,   # repl_env IS the user root; primitive root is internal
        "define-global":  lambda n, v: current_env.find_root().define(str(n), v),
        "bound?":         lambda e, s: _is_bound(e, s),
        "is-bound?":      lambda s: _is_bound(current_env, s),
        "module-keys":    lambda e: list(e.keys()) if isinstance(e, Environment) else [],
        "get-parent":     lambda e: e.parent if isinstance(e, Environment) else None,
        "seal!":          lambda: current_env.__setattr__("sealed", True),
        "is-fixed?":      lambda e, k: k in e.fixed if isinstance(e, Environment) else False,
        "undefine!":      lambda n: current_env.undefine(str(n)),
        "new-env":        lambda: Environment(parent=None),
        "all-symbols":    lambda: (list(current_env.keys()) +
                                   (list(current_env.parent.keys()) if current_env.parent else [])),
        "eval":         None,   # special form — handled in eval_node
        "get-source":   lambda f: getattr(f, 'source', None),
        "get-name":     lambda f: getattr(f, 'name',   None),
        "raw-print": lambda x: (sys.stdout.write(str(x) + "\n"), None)[1],
        # --- Capabilities / effects ---------------------------------------
        "new-capability":    lambda n: Capability(n),
        "new-effect":        lambda n, f: Effect(n, f),
        "grant-capability":  lambda cap: current_env.grant(cap.name),
        "revoke-capability": lambda cap: current_env.revoke(cap.name),
        # --- Macros / reader macros ---------------------------------------
        "register-macro!":        lambda n, p, b: _register_macro(n, p, b, current_env),
        "unregister-reader-macro!": lambda c: READ_TABLE.pop(str(c), None),
        "reset-reader-macros!":   reset_reader_macros,
        "list-reader-macros":     lambda: list(READ_TABLE.keys()),
        # --- Reader -------------------------------------------------------
        "read":           lambda s: read_node(s),
        "next-token":     lambda s: s.next(),
        "read-char":      lambda s: s.next(),
        "tokenize-str":   lambda s: tokenize(s),
        # --- Introspection ------------------------------------------------
        "view-body":   lambda obj: obj.body if hasattr(obj, "body") else repr(obj),
        "view-params": lambda obj: obj.params if hasattr(obj, "params") else [],
        "call-method": lambda obj, m, *a: getattr(obj, m)(*a),
        # --- System -------------------------------------------------------
        "set-recursion-depth": lambda n: sys.setrecursionlimit(int(n)),
        # --- Persistence --------------------------------------------------
        "save-image":      lambda n, e: save_image(n, e),
        "load-image":      lambda n: load_image(n, current_env),
        "set-prelude!":    lambda f: save_config({"prelude_file": f, "prelude_enabled": True}),
        "enable-prelude!": lambda: save_config({"prelude_enabled": True}),
        "disable-prelude!":lambda: save_config({"prelude_enabled": False}),
        "view-config":     load_config,
        "reset-environment!": lambda: reset_environment(),
        "debug-mode":  _make_debug_toggle,
        # --- Paths --------------------------------------------------------
        "omega-home":       get_omega_home,
        "store-path":       get_store_path,
        "config-path":      get_config_path,
        "set-omega-home!":  update_omega_home,
        "set-store-path!":  update_store_path,
        "set-config-path!": update_config_path,
        # --- Sentinels / special-form markers (intercepted by eval_node) -
        "true":     True,
        "false":    False,
        "None":     None,
        "quote":    "quote",
        "evaluate": "evaluate",
        "expand":   "expand",
        "match":    "match",
    }

def _gensym(prefix="g") -> Symbol:
    global GENSYM_COUNT
    GENSYM_COUNT += 1
    return Symbol(f"{prefix}_{GENSYM_COUNT}_")

def _is_bound(env_obj, sym) -> bool:
    if not isinstance(env_obj, Environment): return False
    try: env_obj.find(str(sym)); return True
    except NameError: return False

def _register_macro(name, params, body, current_env):
    current_env.find_root().define(str(name), Macro(params, body, current_env.find_root()))

def compute_hash(ast) -> str:
    return hashlib.sha256(str(ast).encode()).hexdigest()


# ===========================================================================
# ENVIRONMENT BOOTSTRAP
# ===========================================================================

def _set_nested(env: Environment, path: str, value, is_fixed=False):
    """Support dot-notation define: (define Mod.key value)."""
    parts = path.split(".")
    if len(parts) == 1:
        env.define(path, value, is_fixed=is_fixed)
        return
    target = env.find(parts[0])[parts[0]]
    for part in parts[1:-1]:
        if not isinstance(target, Environment):
            raise TypeError(f"'{parts[0]}' is not a Module/Environment")
        target = target[part]
    if not isinstance(target, Environment):
        raise TypeError(f"'{'.'.join(parts[:-1])}' is not a Module/Environment")
    target.define(parts[-1], value, is_fixed=is_fixed)

def initial_environment() -> Environment:
    root     = Environment(parent=None)
    root.bulk_define(_make_primitives(root))
    repl_env = Environment(parent=root)
    # Both current-env and find-root point at repl_env — the top of user space.
    # The primitive root is intentionally hidden; users never need to save it.
    repl_env.define("current-env", lambda: repl_env)
    repl_env.define("find-root",   lambda: repl_env)
    return repl_env

env = initial_environment()

def reset_environment():
    """
    Reset the global environment to a clean slate.
    Re-initializes:
      - Global Environment
      - READ_TABLE with default reader macros
      - Core primitives
    """
    global env, READ_TABLE

    # 1. Create fresh Environment
    env = Environment()

    # 2. Register core primitives
    # core_primitives = {
    #     "+": lambda *args: sum(args),
    #     "-": lambda x, *rest: x - sum(rest) if rest else -x,
    #     "*": lambda *args: eval_mul(args),
    #     "/": lambda x, *rest: eval_div(x, rest),
    #     "list": lambda *args: list(args),
    #     "first": lambda l: l[0] if l else None,
    #     "rest": lambda l: l[1:] if len(l) > 1 else [],
    #     # ... add all other primitives from your prelude
    # }
    env.update(_make_primitives(env))

    # 3. Reset reader macros
    READ_TABLE = {}
    READ_TABLE[";"]  = _semicolon_reader
    READ_TABLE["'"]  = lambda stream: ["quote", read_node(stream)]
    READ_TABLE["`"]  = lambda stream: ["quasiquote", read_node(stream)]
    READ_TABLE[",@"] = lambda stream: ["unquote-splicing", read_node(stream)]
    READ_TABLE[","]  = lambda stream: ["unquote", read_node(stream)]

    return Symbol("ok")

# ===========================================================================
# EVALUATOR
# ===========================================================================

def _make_seq_replay(suf, e):
    """
    Module-level helper for shift/reset continuation capture.
    Returns a replay closure that runs suf[:-1] as side effects and returns suf[-1].
    If a shift fires at position j while replaying, recursively captures
    suf[j+1:] into the new fwd's replay_chain — preserving the full continuation.
    Used by begin, let, let*, letrec body handlers and _make_frame_replay.
    """
    def _sr(v, suf=suf, e=e):
        for j, s in enumerate(suf[:-1]):
            try:
                trampoline(s, e)
            except _ShiftAbort as sa:
                ir = _make_seq_replay(suf[j+1:], e)
                sa.fwd.replay_chain.append(ir)
                if sa.k_invoked:
                    raise _ShiftAbort(sa.fwd, ir(sa.abort_value), k_invoked=True)
                raise
        return trampoline(suf[-1], e) if suf else v
    return _sr


def eval_node(node, env: Environment, _visited):
    # --- Self-evaluating atoms -------------------------------------------
    if node is None:               return None
    if isinstance(node, bool):     return node
    if isinstance(node, (int, float)): return node

    # --- Keyword symbols (:name) -----------------------------------------------
    # Symbols starting with ':' are keyword markers — they self-evaluate.
    # Used as named argument markers in py-call-kw, py-call-method-kw, etc.
    # (py-call-kw "tkinter.Label" root :text "Hello")  →  :text evaluates to Symbol(":text")
    if isinstance(node, Symbol) and str(node).startswith(":"):
        return node   # self-evaluating keyword

    # --- Symbol lookup -------------------------------------------------------
    # Symbol is checked BEFORE plain str — Symbol subclasses str but means "look me up"
    if isinstance(node, Symbol):
        key = str(node)
        if "." in key:
            parts   = key.split(".")
            current = env.find(parts[0])[parts[0]]
            for part in parts[1:]:
                # Accept both Module (new) and Environment (legacy)
                if isinstance(current, Module):
                    try:
                        current = current.lookup(part)
                    except (KeyError, NameError):
                        raise NameError(f"Module '{parts[0]}' has no export '{part}'")
                elif isinstance(current, Environment):
                    current = current[part]
                else:
                    raise TypeError(f"'{parts[0]}' is not a Module/Environment")
            return current
        return env.find(key)[key]

    # --- String literal -------------------------------------------------------
    # StringLiteral carries its content already unescaped; just return it.
    if isinstance(node, StringLiteral):
        return str(node)   # plain Python str — the actual value

    # --- Legacy / sentinel plain str (special-form markers, hydrated AST nodes) -
    # These come from: (a) the primitives dict sentinels like "quote", "evaluate",
    # (b) old serialized images before StringLiteral existed.
    # We still handle them gracefully.
    if isinstance(node, str):
        try:
            return env.find(node)[node]
        except NameError:
            return node   # return as-is (special-form sentinel)

    # --- Non-list atoms ---------------------------------------------------
    if not isinstance(node, list) or len(node) == 0:
        return node

    op = node[0]

    # =====================================================================
    # SPECIAL FORMS
    # =====================================================================

    if op == "quote":
        return node[1]

    elif op == "quasiquote":
        return eval_node(quasiquote_expand(node[1]), env, _visited)

    elif op == "unquote" or op == "unquote-splicing":
        raise SyntaxError(f"{op} used outside of quasiquote")

    elif op == "if":
        _, cond, t, *rest = node
        f = rest[0] if rest else None
        # Use trampoline to fully resolve the boolean value
        is_true = is_lisp_true(trampoline(cond, env))
        return eval_node(t if is_true else f, env, _visited)

    elif op == "cond":
        for clause in node[1:]:
            test    = clause[0]
            actions = clause[1:]   # may be multiple expressions — implicit begin
            if test == "else" or is_lisp_true(trampoline(test, env)):
                for act in actions[:-1]:
                    trampoline(act, env)
                return eval_node(actions[-1], env, _visited) if actions else None
        return None

    elif op == "and":
        result = True
        for expr in node[1:]:
            result = trampoline(expr, env)
            if not is_lisp_true(result): return result
        return result

    elif op == "or":
        for expr in node[1:]:
            result = trampoline(expr, env)
            if is_lisp_true(result): return result
        return False
        return False

    elif op == "not":
        return not is_lisp_true(trampoline(node[1], env))

    elif op == "let":
        bindings = node[1]
        let_env  = Environment(parent=env)
        let_env.opened_modules = list(env.opened_modules)
        for bi, b in enumerate(bindings):
            try:
                let_env.define(str(b[0]), trampoline(b[1], env))
            except _ShiftAbort as sa:
                # Shift in binding bi's value. The continuation needs to:
                # 1. evaluate remaining bindings[bi+1:] into let_env
                # 2. then run the body
                remaining_bindings = bindings[bi+1:]
                body_for_cont = node[2:]
                def _let_bind_replay(v, rb=remaining_bindings, le=let_env,
                                     orig_env=env, body=body_for_cont, bname=str(b[0])):
                    le.define(bname, v)
                    for nb in rb:
                        le.define(str(nb[0]), trampoline(nb[1], orig_env))
                    for expr in body[:-1]: trampoline(expr, le)
                    return trampoline(body[-1], le) if body else None
                sa.fwd.replay_chain.append(_let_bind_replay)
                if sa.k_invoked:
                    raise _ShiftAbort(sa.fwd, _let_bind_replay(sa.abort_value), k_invoked=True)
                raise
        body = node[2:]
        for i, expr in enumerate(body[:-1]):
            try:
                trampoline(expr, let_env)
            except _ShiftAbort as sa:
                replay = _make_seq_replay(body[i+1:], let_env)
                sa.fwd.replay_chain.append(replay)
                if sa.k_invoked:
                    raise _ShiftAbort(sa.fwd, replay(sa.abort_value), k_invoked=True)
                raise
            except _KInvoked as ki:
                replay = _make_seq_replay(body[i+1:], let_env)
                ki.fwd.replay_chain.append(replay)
                applied = ki.fwd._apply_chain(ki.applied_value)
                ki.fwd._capturing = False; ki.fwd._make_real()
                raise _ShiftAbort(ki.fwd, applied, k_invoked=True)
        return eval_node(body[-1], let_env, _visited) if body else None

    elif op == "let*":
        bindings = node[1]
        let_env  = Environment(parent=env)
        let_env.opened_modules = list(env.opened_modules)
        for bi, b in enumerate(bindings):
            try:
                let_env.define(str(b[0]), trampoline(b[1], let_env))
            except _ShiftAbort as sa:
                remaining_bindings = bindings[bi+1:]
                body_for_cont = node[2:]
                def _lstar_bind_replay(v, rb=remaining_bindings, le=let_env,
                                       body=body_for_cont, bname=str(b[0])):
                    le.define(bname, v)
                    for nb in rb: le.define(str(nb[0]), trampoline(nb[1], le))
                    for expr in body[:-1]: trampoline(expr, le)
                    return trampoline(body[-1], le) if body else None
                sa.fwd.replay_chain.append(_lstar_bind_replay)
                if sa.k_invoked:
                    raise _ShiftAbort(sa.fwd, _lstar_bind_replay(sa.abort_value), k_invoked=True)
                raise
        body = node[2:]
        for i, expr in enumerate(body[:-1]):
            try:
                trampoline(expr, let_env)
            except _ShiftAbort as sa:
                replay = _make_seq_replay(body[i+1:], let_env)
                sa.fwd.replay_chain.append(replay)
                if sa.k_invoked:
                    raise _ShiftAbort(sa.fwd, replay(sa.abort_value), k_invoked=True)
                raise
            except _KInvoked as ki:
                replay = _make_seq_replay(body[i+1:], let_env)
                ki.fwd.replay_chain.append(replay)
                applied = ki.fwd._apply_chain(ki.applied_value)
                ki.fwd._capturing = False; ki.fwd._make_real()
                raise _ShiftAbort(ki.fwd, applied, k_invoked=True)
        return eval_node(body[-1], let_env, _visited) if body else None

    elif op == "letrec":
        bindings = node[1]
        let_env  = Environment(parent=env)
        let_env.opened_modules = list(env.opened_modules)
        for b in bindings: let_env.define(str(b[0]), None)
        for b in bindings: let_env.mutate(str(b[0]), trampoline(b[1], let_env))
        body = node[2:]
        for i, expr in enumerate(body[:-1]):
            try:
                trampoline(expr, let_env)
            except _ShiftAbort as sa:
                replay = _make_seq_replay(body[i+1:], let_env)
                sa.fwd.replay_chain.append(replay)
                if sa.k_invoked:
                    raise _ShiftAbort(sa.fwd, replay(sa.abort_value), k_invoked=True)
                raise
            except _KInvoked as ki:
                replay = _make_seq_replay(body[i+1:], let_env)
                ki.fwd.replay_chain.append(replay)
                applied = ki.fwd._apply_chain(ki.applied_value)
                ki.fwd._capturing = False; ki.fwd._make_real()
                raise _ShiftAbort(ki.fwd, applied, k_invoked=True)
        return eval_node(body[-1], let_env, _visited) if body else None

    elif op == "define":
        if isinstance(node[1], list):
            # Shorthand: (define (fname param...) body...)
            fname     = str(node[1][0])
            params    = node[1][1:]
            body_list = node[2:]
            body_expr = ["begin"] + body_list if len(body_list) > 1 else body_list[0]
            # Store source as (lambda (params...) body...) for transpiler use
            source    = [Symbol("lambda"), params] + body_list
            func      = Lambda(params, body_expr, env, name=fname, source=source)
            _set_nested(env, fname, func)
            return func
        else:
            # Standard: (define name expr)
            name = str(node[1])
            val  = trampoline(node[2], env)
            if isinstance(val, Lambda) and val.name is None:
                val.name = name   # tag anonymous lambdas with their binding name
            _set_nested(env, name, val)
            return val

    elif op == "define-const":
        val = trampoline(node[2], env)
        _set_nested(env, str(node[1]), val, is_fixed=True)
        return val

    elif op == "set!":
        val  = trampoline(node[2], env)
        raw  = str(node[1]) if isinstance(node[1], (str, Symbol)) else str(trampoline(node[1], env))
        if "." in raw:
            # Dotted mutation: (set! a.b.c val)
            # Walk the path, mutate the final key in the final Module/Environment.
            parts = raw.split(".")
            # Resolve all but the last part to get the target container
            current = env.find(parts[0])[parts[0]]
            for part in parts[1:-1]:
                if isinstance(current, Module):
                    current = current.lookup(part)
                elif isinstance(current, Environment):
                    current = current[part]
                else:
                    raise TypeError(f"(set!): '{'.'.join(parts[:-1])}' is not a Module/Environment")
            last = parts[-1]
            if isinstance(current, Module):
                # Mutate directly in the module's env
                try:
                    frame = current.env.find(last)
                    frame[last] = val
                except NameError:
                    # Key not yet in module — define it
                    current.env.define(last, val)
            elif isinstance(current, Environment):
                try:
                    current.mutate(last, val)
                except NameError:
                    current.define(last, val)
            else:
                raise TypeError(f"(set!): cannot mutate into {type(current).__name__}")
        else:
            env.mutate(raw, val)
        return val

    elif op == "begin":
        exprs = node[1:]
        for i, expr in enumerate(exprs[:-1]):
            try:
                trampoline(expr, env)
            except _ShiftAbort as sa:
                replay = _make_seq_replay(exprs[i+1:], env)
                sa.fwd.replay_chain.append(replay)
                if sa.k_invoked:
                    raise _ShiftAbort(sa.fwd, replay(sa.abort_value), k_invoked=True)
                raise
            except _KInvoked as ki:
                replay = _make_seq_replay(exprs[i+1:], env)
                ki.fwd.replay_chain.append(replay)
                applied = ki.fwd._apply_chain(ki.applied_value)
                ki.fwd._capturing = False; ki.fwd._make_real()
                raise _ShiftAbort(ki.fwd, applied, k_invoked=True)
        return eval_node(exprs[-1], env, _visited) if exprs else None

    elif op == "lambda":
        params      = node[1]
        raw_body    = node[2:]
        effects, body = [], []
        for expr in raw_body:
            if isinstance(expr, list) and expr[0] == ":effects":
                effects.extend(expr[1:])
            else:
                body.append(expr)
        body_expr = ["begin"] + body if len(body) > 1 else body[0]
        return Lambda(params, body_expr, env, required_effects=effects, source=node)

    elif op == "macro":
        # (macro (params) body)       — anonymous macro expression
        # (macro name (params) body)  — named, defines in current env
        if len(node) == 3:
            return Macro(node[1], node[2], env)
        elif len(node) == 4:
            m = Macro(node[2], node[3], env)
            env.define(str(node[1]), m)
            return m
        else:
            raise SyntaxError("(macro [name] (params) body)")

    elif op == "register-macro!":
        # (register-macro! name (params) body)
        # (register-macro! 'name '(params) 'body)  — with quotes
        # name can be a symbol or (quote symbol)
        # params/body: strip one (quote ...) wrapper if present; leave raw AST.
        # We do NOT fully evaluate body — it must stay as unevaluated AST.
        raw_name = node[1]
        name = eval_node(raw_name, env, _visited) if isinstance(raw_name, list) else str(raw_name)
        if not isinstance(name, str):
            raise TypeError(f"register-macro! name must be a string, got {type(name)}")
        def unwrap_quote(n):
            if isinstance(n, list) and len(n) == 2 and str(n[0]) == "quote":
                return n[1]
            return n
        params = unwrap_quote(node[2])
        body   = unwrap_quote(node[3])
        env.find_root().define(name, Macro(params, body, env.find_root()))
        return None


    elif op == "while":
        cond, body = node[1], node[2]
        # Resolve condition every iteration
        while trampoline(cond, env):
            eval_node(body, env, set())
        return None

    elif op == "match":
        for clause in node[1:]:
            test, action = clause
            if trampoline(test, env):
                return eval_node(action, env, _visited)
        return None

    elif op == "evaluate":
        return eval_node(eval_node(node[1], env, _visited), env, _visited)

    elif op == "expand":
        # (expand '(macro-call args...))
        # Returns the macro-expanded form as a data structure (not evaluated).
        # Uses syntactic substitution so (expand '(my-inc 5)) → (+ 5 1) as a list.
        form = eval_node(node[1], env, _visited)
        if not isinstance(form, list) or not form:
            return form
        head = form[0]
        head_val = None
        if isinstance(head, (str, Symbol)):
            try: head_val = env.find_root().find(str(head))[str(head)]
            except NameError: pass
        if isinstance(head_val, Macro):
            macro   = head_val
            args    = form[1:]
            subs    = {str(p): a for p, a in zip(macro.params, args)}
            def subst(n):
                if isinstance(n, (str, Symbol)) and str(n) in subs:
                    return subs[str(n)]
                if isinstance(n, list):
                    return [subst(x) for x in n]
                return n
            # For quasiquote bodies, we need to eval the body with params bound
            # then substitute. For quote bodies, just substitute directly.
            body = macro.body
            if isinstance(body, list) and str(body[0]) == "quasiquote":
                # eval with substituted params to resolve quasiquote
                menv = Environment(parent=macro.env)
                for p, a in zip(macro.params, args):
                    menv.define(str(p), a)
                return eval_node(body, menv, set())
            else:
                return subst(body)
        return form  # not a macro — return as-is

    elif op == "undefine!":
        return env.undefine(str(node[1]))


    elif op == "module":
        # (module Name body...)
        # Creates an isolated module environment, evaluates all body forms,
        # then wraps in a Module object.  The module name is bound in the
        # calling env as a Module (not a raw Environment).
        mod_name = str(node[1])
        mod_env  = Environment(parent=env)   # parent during eval (can see caller's primitives)
        mod_env.opened_modules = []          # no inherited opened chain
        explicit_exports = None              # set by (export ...) inside the module body
        for expr in node[2:]:
            # Detect (export sym1 sym2 ...) — sets explicit export list
            if isinstance(expr, list) and len(expr) > 0 and str(expr[0]) == "export":
                explicit_exports = [str(s) for s in expr[1:]]
            else:
                trampoline(expr, mod_env)
        mod_env.opened_modules = []         # clear after execution (prevents find cycles)
        mod = Module(name=mod_name, env=mod_env, origin="file",
                     exports=explicit_exports)
        env.define(mod_name, mod)
        return mod

    elif op == "export":
        # (export sym1 sym2 ...)
        # Sets the explicit export list on the nearest enclosing module.
        # As a standalone form this is a no-op — it's processed inside (module ...).
        return None

    elif op == "memoize!":
        # (memoize! 'name)  — quoted symbol, OR
        # (memoize! name)   — unquoted bare symbol (not evaluated further)
        #
        # We always want the *name* (string key) not the function value,
        # so we extract the symbol without evaluating it.

        arg = node[1]
        if isinstance(arg, list) and len(arg) == 2 and str(arg[0]) == "quote":
            # (memoize! 'fname) — explicit quote
            key = str(arg[1])
        elif isinstance(arg, (str, Symbol)):
            # (memoize! fname) — bare symbol: use as-is without evaluating
            # Dot paths like 'v.fib' are NOT supported here — use set! for that
            key = str(arg)
        else:
            raise TypeError("memoize! expects a symbol name, e.g. (memoize! 'fib) or (memoize! fib)")

        frame = env.find(key)
        f     = frame[key]
        if getattr(f, '_is_memoized', False):
            return f   # idempotent

        wrapper = _make_memoized_wrapper(f, env)
        # Rebind in the calling-env frame
        frame[key] = wrapper
        # Rebind in every frame in the Lambda's closure chain.
        # We replace ANY name that still points to the original function f —
        # this handles aliases: (define copy orig) + (memoize! copy) correctly
        # rebinds both `copy` and `orig` (and any other aliases) so the body's
        # recursive calls go through the memoized wrapper regardless of which
        # name they use.
        if isinstance(f, Lambda):
            visited = set()
            cursor  = f.env
            while cursor is not None:
                fid = id(cursor)
                if fid in visited: break
                visited.add(fid)
                for k2, v2 in list(cursor.items()):
                    if v2 is f:
                        cursor[k2] = wrapper
                cursor = cursor.parent
        return wrapper

    elif op == "memoize-rec!":
        # (memoize-rec! '(f g h))  — memoize a group of mutually-recursive
        # functions atomically.  All wrappers are installed before any call
        # so each function sees the memoized versions of all its partners.
        names_arg = trampoline(node[1], env)
        if not isinstance(names_arg, list):
            raise TypeError("memoize-rec! expects a list of quoted names")
        keys = [str(n) for n in names_arg]

        # Collect all original functions first
        originals = {}
        for key in keys:
            frame = env.find(key)
            originals[key] = (frame, frame[key])

        # Build all wrappers (they share a combined cache dict per function)
        wrappers = {}
        for key, (frame, f) in originals.items():
            if getattr(f, '_is_memoized', False):
                wrappers[key] = f   # already done
            else:
                wrappers[key] = _make_memoized_wrapper(f, env)

        # Install ALL wrappers before returning — atomic rebind
        for key, (frame, f) in originals.items():
            frame[key] = wrappers[key]
            if isinstance(f, Lambda):
                try:
                    closure_frame = f.env.find(key)
                    closure_frame[key] = wrappers[key]
                except NameError:
                    pass

        return list(wrappers.values())

    elif op == "open":
        # (open mod)  — import all public exports of a module into this env.
        # Copies names directly into the calling env; does NOT register the
        # module in opened_modules (that would cause infinite recursion in find
        # when the module's env has a parent that leads back to this env).
        target = eval_node(node[1], env, _visited)
        if isinstance(target, Module):
            for k in target.public_keys():
                try:
                    env.define(k, target.lookup(k))
                except Exception:
                    pass
        elif isinstance(target, Environment):
            for k, v in target.items():
                env.define(k, v)
        else:
            raise TypeError(
                f"Can only 'open' a Module or Environment, got {type(target).__name__}"
            )
        return None

    elif op == "with-module":
        # (with-module mod body...)
        # Like (open mod) but scoped: exports are visible only within body.
        # The calling env is not modified after body completes.
        target = eval_node(node[1], env, _visited)
        scoped_env = Environment(parent=env)
        scoped_env.opened_modules = list(env.opened_modules)
        if isinstance(target, Module):
            for k in target.public_keys():
                try:
                    scoped_env.define(k, target.lookup(k))
                except Exception:
                    pass
        elif isinstance(target, Environment):
            for k, v in target.items():
                scoped_env.define(k, v)
        else:
            raise TypeError(
                f"with-module: expected a Module or Environment, got {type(target).__name__}"
            )
        body = node[2:]
        for expr in body[:-1]: trampoline(expr, scoped_env)
        return eval_node(body[-1], scoped_env, _visited) if body else None

    elif op == "load":
        # Unlike (import ...) which creates a module namespace, (load ...) is
        # like pasting the file into the REPL at this point.
        #
        # Reader-macro isolation: user-registered reader macros (those with a
        # .lisp_handler attribute) are temporarily removed before parsing so
        # that a previously-active macro like `~` cannot corrupt the re-reading
        # of a file that also registers `~`.  The file's own registrations take
        # effect as they execute (they modify READ_TABLE at eval time, not parse
        # time), and the full READ_TABLE is restored on exit so the REPL session
        # keeps any macros the file registered.
        file_path = str(trampoline(node[1], env)).strip('"')
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"(load): file not found: {file_path}")
        with open(file_path) as f: content = f.read()
        # Snapshot and strip user-defined reader macros for clean parsing
        user_macros = {k: v for k, v in READ_TABLE.items()
                       if hasattr(v, "lisp_handler")}
        for k in user_macros: del READ_TABLE[k]
        try:
            stream = Stream(tokenize(content))
            last_result = None
            while stream.peek() is not None:
                ast = read_node(stream)
                if ast is not None:
                    last_result = trampoline(ast, env)
        finally:
            # Restore user macros that were active before the load.
            # Macros registered BY this load are already in READ_TABLE.
            for k, v in user_macros.items():
                if k not in READ_TABLE:      # don't clobber newly registered ones
                    READ_TABLE[k] = v
        return last_result

    elif op == "import":
        # (import "name" alias?)
        #
        # Resolution order (via ModuleResolver):
        #   1. Native host module (sys, re, os, math, …) → Module(origin="native")
        #   2. Lisp .ol file                             → Module(origin="file")
        #   3. Unknown                                   → FileNotFoundError
        #
        # Returns a Module object — never a raw dict or Environment.
        # The alias is bound in the calling env; nothing else leaks.
        raw_name = str(eval_node(node[1], env, _visited)).strip('"')
        alias    = str(node[2]) if len(node) > 2 else raw_name

        kind, value = _module_resolver.resolve(raw_name)

        if kind == "native":
            # Wrap the Python module object in a thin Module so callers
            # always get the same type regardless of origin.
            mod_env = Environment(parent=None)
            mod_env.define("__native__", value)
            # Also inject the module's public attributes for (getattr mod x)
            mod = Module(name=raw_name, env=mod_env, origin="native")
            # Store the raw Python module as a special attr for getattr chains
            mod._native = value
            env.define(alias, mod)
            return mod

        elif kind == "file":
            file_path  = value
            module_env = Environment(parent=env.find_root())
            module_env.opened_modules = []
            with open(file_path) as f: content = f.read()
            # Reader-macro isolation: strip user-registered reader macros before
            # parsing so that macros active in the REPL (like `~`) don't corrupt
            # files that also register or use the same characters.
            user_macros = {k: v for k, v in READ_TABLE.items()
                           if hasattr(v, "lisp_handler")}
            for k in user_macros: del READ_TABLE[k]
            try:
                # Pre-scan for a top-level (export ...) declaration.
                file_exports = None
                pre_stream = Stream(tokenize(content))
                while pre_stream.peek() is not None:
                    form = read_node(pre_stream)
                    if (isinstance(form, list) and len(form) > 0
                            and str(form[0]) == "export"):
                        file_exports = [str(s) for s in form[1:]]
                        break
                stream = Stream(tokenize(content))
                while stream.peek() is not None:
                    ast = read_node(stream)
                    if ast: trampoline(ast, module_env)
            finally:
                for k, v in user_macros.items():
                    if k not in READ_TABLE:
                        READ_TABLE[k] = v
            module_env.opened_modules = []

            # Unwrap: if the file's top-level env contains exactly ONE Module
            # binding (the common pattern: one (module Name ...) per file),
            # surface that inner Module directly rather than double-wrapping.
            public = [k for k in module_env.keys()
                      if not k.startswith("_")]
            if (len(public) == 1
                    and isinstance(module_env[public[0]], Module)):
                inner = module_env[public[0]]
                env.define(alias, inner)
                return inner

            mod = Module(name=raw_name, env=module_env, origin="file",
                         exports=file_exports)
            env.define(alias, mod)
            return mod

        else:
            raise FileNotFoundError(
                f"(import): cannot resolve '{raw_name}' — "
                f"not a known native module and no file found. "
                f"To register a native module: "
                f"_module_resolver.register('lang', {{'{raw_name}'}})"
            )

    # ── Forms produced by python_to_lisp.py ────────────────────────────────
    # These allow lifted Python files to be loaded without errors.

    elif op == "import-native":
        # (import-native "sys" sys)
        # Resolve unconditionally as a native/host module, return a Module.
        raw_name = str(eval_node(node[1], env, _visited)).strip('"')
        alias    = str(node[2]) if len(node) > 2 else raw_name.replace(".", "_")
        native   = _module_resolver.resolve_native(raw_name)
        if native is not None:
            mod_env = Environment(parent=None)
            mod_env.define("__native__", native)
            mod = Module(name=raw_name, env=mod_env, origin="native")
            mod._native = native
            env.define(alias, mod)
            return mod
        return None   # soft failure — module not installed

    elif op == "import-from":
        # (import-from "module" "name" alias)
        # Use Python's __import__ to pull the name into Omega's env.
        mod_name  = str(trampoline(node[1], env)).strip('"')
        item_name = str(trampoline(node[2], env)).strip('"')
        alias     = str(node[3]) if len(node) > 3 else item_name
        try:
            mod = __import__(mod_name, fromlist=[item_name])
            val = getattr(mod, item_name)
            env.define(alias, val)
            return val
        except Exception:
            return None   # soft failure — annotation only

    elif op == "class":
        # (class Name (Base...) body...)
        # We don't build real Python classes; just register the name as a marker.
        name = str(node[1])
        env.define(name, Symbol(name))
        return Symbol(name)

    elif op == "when":
        # (when test body...)  —  if test is true, evaluate body forms
        test = trampoline(node[1], env)
        if is_lisp_true(test):
            result = None
            for expr in node[2:]: result = trampoline(expr, env)
            return result
        return None

    elif op == "try":
        # (try body (handler ExcType name body...) ...)
        body     = node[1]
        handlers = node[2:]
        try:
            return trampoline(body, env)
        except Exception as exc:
            for h in handlers:
                if not (isinstance(h, list) and len(h) >= 3 and h[0] == "handler"):
                    continue
                exc_type_name = str(h[1])
                exc_var       = str(h[2])
                handler_body  = h[3:]
                # Check exception type match
                try:
                    exc_type = eval(exc_type_name)  # resolve built-in names
                except:
                    exc_type = Exception
                if isinstance(exc, exc_type):
                    h_env = Environment(parent=env)
                    h_env.define(exc_var, exc)
                    result = None
                    for expr in handler_body: result = trampoline(expr, h_env)
                    return result
            raise  # re-raise if no handler matched

    elif op == "handler":
        # Standalone handler nodes are only valid inside (try ...).
        # If we see one outside, it's a no-op.
        return None

    elif op == "with":
        # (with (expr name) body)  →  Python 'with expr as name'
        # Each pair before the body is a context binding.
        # The last element is the body.
        items = node[1:-1]
        body  = node[-1]
        ctx_stack = []
        with_env = Environment(parent=env)
        try:
            for item in items:
                if isinstance(item, list) and len(item) == 2:
                    ctx_obj = trampoline(item[0], env)
                    var_name = str(item[1])
                    entered  = ctx_obj.__enter__() if hasattr(ctx_obj, '__enter__') else ctx_obj
                    ctx_stack.append(ctx_obj)
                    with_env.define(var_name, entered)
            result = trampoline(body, with_env)
        except Exception as exc:
            for ctx in reversed(ctx_stack):
                if hasattr(ctx, '__exit__'): ctx.__exit__(type(exc), exc, None)
            raise
        else:
            for ctx in reversed(ctx_stack):
                if hasattr(ctx, '__exit__'): ctx.__exit__(None, None, None)
        return result

    elif op == "assert":
        # (assert test msg?)
        test = trampoline(node[1], env)
        if not is_lisp_true(test):
            msg = trampoline(node[2], env) if len(node) > 2 else "assertion failed"
            raise AssertionError(str(msg))
        return None

    elif op == "getattr":
        # (getattr obj attr)  →  obj.attr
        # If obj is a native Module, delegate to the wrapped Python module.
        obj  = trampoline(node[1], env)
        attr = node[2] if isinstance(node[2], (str, Symbol)) else trampoline(node[2], env)
        # Unwrap native modules so (getattr sys version) → sys.version
        target = getattr(obj, "_native", obj) if isinstance(obj, Module) else obj
        return getattr(target, str(attr))

    elif op == "get":
        # (get obj key)  →  obj[key]
        obj = trampoline(node[1], env)
        key = trampoline(node[2], env)
        return obj[key]

    elif op == "isinstance":
        # (isinstance obj Type)  →  Python isinstance(obj, Type)
        obj  = trampoline(node[1], env)
        typ  = trampoline(node[2], env)
        return isinstance(obj, typ)

    elif op == "kw":
        # (kw name val)  →  keyword argument placeholder; just return val
        # Keyword args in generic calls aren't supported structurally, but
        # many lifted files use them. Return the value silently.
        return trampoline(node[2], env)

    elif op == "is":
        # (is a b)  →  a is b
        a = trampoline(node[1], env)
        b = trampoline(node[2], env)
        return a is b

    elif op == "is-not":
        # (is-not a b)  →  a is not b
        a = trampoline(node[1], env)
        b = trampoline(node[2], env)
        return a is not b

    elif op == "in":
        # (in a b)  →  a in b
        a = trampoline(node[1], env)
        b = trampoline(node[2], env)
        return a in b

    elif op == "not-in":
        # (not-in a b)  →  a not in b
        a = trampoline(node[1], env)
        b = trampoline(node[2], env)
        return a not in b

    elif op == "slice":
        # (slice start stop step)  →  Python slice object
        start = trampoline(node[1], env)
        stop  = trampoline(node[2], env)
        step  = trampoline(node[3], env) if len(node) > 3 else None
        return slice(start, stop, step)

    elif op == "tuple":
        # (tuple a b ...)  →  Python tuple
        return tuple(trampoline(x, env) for x in node[1:])

    elif op == "set":
        # (set a b ...)  →  Python set
        return {trampoline(x, env) for x in node[1:]}

    elif op == "dict":
        # (dict (pair k v) ...)  →  Python dict
        d = {}
        for item in node[1:]:
            if isinstance(item, list) and len(item) == 3 and item[0] == "pair":
                k = trampoline(item[1], env)
                v = trampoline(item[2], env)
                d[k] = v
            elif isinstance(item, list) and len(item) == 3 and item[0] == "**spread":
                d.update(trampoline(item[1], env))
        return d

    elif op == "list":
        # (list a b ...)  →  Python list  (the form, not the builtin)
        return [trampoline(x, env) for x in node[1:]]

    elif op == "pair":
        # (pair k v)  →  [k, v]  (used inside dict)
        return [trampoline(node[1], env), trampoline(node[2], env)]

    elif op == "stream":
        # (stream expr)  →  treat as list (eager evaluation, not lazy)
        return list(trampoline(node[1], env))

    elif op == "delete!":
        # (delete! name ...)  →  del name in current scope
        for target in node[1:]:
            key = str(target) if isinstance(target, Symbol) else str(trampoline(target, env))
            try: env.undefine(key)
            except: pass
        return None

    elif op == "global" or op == "nonlocal":
        # (global name ...)  →  no-op in Omega's environment model
        return None

    elif op == "python-opaque":
        # (python-opaque TypeName)  →  placeholder for unsupported constructs
        return None

    elif op == "seal-with-sig":
        mod  = eval_node(node[1], env, _visited)
        sig  = eval_node(node[2], env, _visited)
        out  = Environment(parent=None)
        for sym in sig:
            if sym in mod: out.define(sym, mod[sym])
        return out

    elif op == "with-capability":
        cap = eval_node(node[1], env, _visited)
        if isinstance(cap, Resource) and cap.linear:
            if cap.consumed: raise NameError(f"Linear Violation: capability already consumed.")
            cap.consumed = True
        new_env = Environment(parent=env)
        new_env.capabilities.add(cap.name)
        result = None
        for expr in node[2:]: result = eval_node(expr, new_env, _visited)
        return result

    elif op == "string-literal":
        return str(node[1]).strip('"')

    elif op == "eval":
        # (eval expr) — evaluate expr then evaluate the result in the current env
        val = trampoline(node[1], env)
        return trampoline(val, env)

    elif op == "defined?":
        # (defined? 'sym) — True if sym is bound in the current environment
        sym = trampoline(node[1], env)
        try:
            env.find(str(sym))
            return True
        except NameError:
            return False

    # ─── Delimited continuations (shift / reset) ──────────────────────────
    #
    # Implementation strategy:
    #   shift raises _ShiftAbort(cont, abort_value) to unwind to the nearest reset.
    #   reset catches _ShiftAbort and returns abort_value.
    #   The continuation replay_fn is built by the FUNCTION-CALL handler:
    #   when evaluating args for a call and a _ShiftAbort fires mid-arg,
    #   we catch it and wrap a replay closure that:
    #     - re-calls the function with already-evaluated prefix args,
    #       the continuation value, then evaluates remaining args.
    #   This correctly captures one frame of the call-chain per reset boundary.
    #   Nested resets capture nested frames — this is compositionally correct.

    elif op == "reset":
        try:
            return trampoline(node[1], env)
        except _ShiftAbort as sa:
            sa.fwd._capturing = False
            sa.fwd._make_real()
            return sa.abort_value

    elif op == "effect-handle":
        # (effect-handle handlers thunk)
        # Python-level algebraic effect handler with correct nested composition.
        # handlers: list of (list 'handler eff-tag handler-fn)
        # thunk:    zero-arg Lambda
        hv = trampoline(node[1], env)
        tv = trampoline(node[2], env)

        def _cf(f, al):
            r = apply(f, al, env, set())
            while isinstance(r, TailCall): r = eval_node(r.expr, r.env, set())
            return r

        def _mt(fn):
            class _T:
                params=[]; body=None; required_effects=[]
                def __init__(s, f): s._f = f; s.env = env
                def __call__(s): return s._f()
            return _T(fn)

        def _eh(hs, tf):
            while True:
                try:
                    res = _cf(tf, [])
                except _ShiftAbort as sa:
                    sa.fwd._capturing = False; sa.fwd._make_real()
                    sig = sa.abort_value
                else:
                    sig = res
                if not (isinstance(sig, list) and len(sig) >= 4 and
                        str(sig[0]) == 'effect-signal'):
                    return sig
                et = sig[1]
                ea = list(sig[2]) if isinstance(sig[2], list) else []
                ct = sig[3]
                mt = [h for h in hs if isinstance(h, list) and len(h) >= 3
                      and str(h[1]) == str(et)]
                if not mt:
                    # No handler — propagate to outer, but wrap cont so resumed
                    # computation re-enters our handlers for remaining effects.
                    def _rc(v, _c=ct, _hs=hs):
                        return _eh(_hs, _mt(lambda: _c(v)))
                    nf = _Fwd(); nf._capturing = False
                    nf.replay_chain.append(lambda v, c=_rc: c(v)); nf._make_real()
                    raise _ShiftAbort(nf, ['effect-signal', et, ea, _rc])
                hf = mt[0][2]
                def _mk(cc, hs2):
                    return lambda v: _eh(hs2, _mt(lambda: cc(v)))
                k = _mk(ct, hs)
                tf = _mt(lambda f=hf, a=ea, kk=k: _cf(f, a + [kk]))

        return _eh(hv, tv)

    elif op == "shift":
        k_name   = str(node[1])
        body_ast = node[2]
        fwd = _Fwd()
        body_env = Environment(parent=env)
        body_env.opened_modules = list(env.opened_modules)
        body_env.define(k_name, fwd)
        try:
            abort_value = trampoline(body_ast, body_env)
            # Pure abort — don't call _make_real yet; frames haven't run yet.
            # _make_real is called by the final frame handler or lazily on first resume.
            raise _ShiftAbort(fwd, abort_value, k_invoked=False)
        except _KInvoked as ki:
            raise _ShiftAbort(ki.fwd, ki.applied_value, k_invoked=True)

    elif op == "continuation?":
        return _is_continuation(trampoline(node[1], env))

    elif op == "multi-shot!":
        k = trampoline(node[1], env)
        if not _is_continuation(k):
            raise TypeError(f"multi-shot! expects a continuation, got {type(k).__name__}")
        return _make_multi_shot(k)

    # =====================================================================
    # FUNCTION / MACRO APPLICATION
    # =====================================================================

    else:
        func = trampoline(node[0], env)

        if isinstance(func, Macro):
            expanded = macro_expand(func, node[1:], env)
            return TailCall(expanded, env)

        # Evaluate args one by one, catching continuation signals.
        #
        # _KInvoked: (k v) fired inside this arg.
        #   We have the prefix (already evaluated) and can build the context.
        #   replay(v) = func(prefix + [v] + eval(suffix))
        #   Apply immediately: result = replay(ki.applied_value)
        #   Abort to reset with that result.
        #
        # _ShiftAbort from a nested shift (k not yet called, pure abort):
        #   Same structure: build replay, add it to fwd's chain.
        #   New abort value = replay(sa.abort_value).
        #   Re-raise with updated abort_value.
        raw_args = node[1:]
        evaled   = []

        def _make_frame_replay(f, pre, suf, e):
            """replay(v) → call f with pre + [v] + eval(suf).
            If a shift fires while evaluating a suffix arg, recursively captures
            the remaining suffix into the new fwd's chain."""
            def replay(v):
                evaled_suf = []
                for j, raw in enumerate(suf):
                    try:
                        evaled_suf.append(trampoline(raw, e))
                    except _ShiftAbort as sa:
                        nr = _make_frame_replay(f, pre+[v]+evaled_suf, suf[j+1:], e)
                        sa.fwd.replay_chain.append(nr)
                        if sa.k_invoked:
                            raise _ShiftAbort(sa.fwd, nr(sa.abort_value), k_invoked=True)
                        raise
                args_full = pre + [v] + evaled_suf
                r = apply(f, args_full, e, set())
                while isinstance(r, TailCall):
                    r = eval_node(r.expr, r.env, set())
                return r
            return replay

        abort_exc = None
        for i, raw in enumerate(raw_args):
            try:
                evaled.append(trampoline(raw, env))
            except _KInvoked as ki:
                # (k v) fired in arg i — build frame context and apply it
                prefix  = list(evaled)
                suffix  = raw_args[i + 1:]
                replay  = _make_frame_replay(func, prefix, suffix, env)
                ki.fwd.replay_chain.append(replay)
                applied = ki.fwd._apply_chain(ki.applied_value)
                ki.fwd._capturing = False
                ki.fwd._make_real()
                abort_exc = _ShiftAbort(ki.fwd, applied, k_invoked=True)
                break
            except _ShiftAbort as sa:
                prefix  = list(evaled)
                suffix  = raw_args[i + 1:]
                replay  = _make_frame_replay(func, prefix, suffix, env)
                # Always add frame to continuation's chain (for when k IS called)
                sa.fwd.replay_chain.append(replay)
                if sa.k_invoked:
                    # k was already called upstream — apply context to get new abort
                    new_abort = replay(sa.abort_value)
                    abort_exc = _ShiftAbort(sa.fwd, new_abort, k_invoked=True)
                else:
                    # Pure abort — do NOT apply context; pass abort_value unchanged
                    abort_exc = _ShiftAbort(sa.fwd, sa.abort_value, k_invoked=False)
                break

        if abort_exc is not None:
            raise abort_exc

        return apply(func, evaled, env, _visited)


# ===========================================================================
# READER HELPERS
# ===========================================================================

def balance(text: str) -> int:
    b = 0
    for t in tokenize(text):
        if t == "(": b += 1
        elif t == ")": b -= 1
    return b

def read_expression(prompt=PROMPT, cont=CONTINUATION) -> str:
    buf = ""
    while True:
        p    = prompt if balance(buf) == 0 else cont
        line = session.prompt(p)
        buf += line + " "
        if balance(buf) == 0:
            return buf.strip()


# ===========================================================================
# REPL
# ===========================================================================

def multiline_repl():
    sys.setrecursionlimit(10000)   # deep AST transpilation needs headroom
    print("Omega Lisp v30 — type 'exit' to quit")
    load_prelude(env)
    while True:
        try:
            line = read_expression()
            if not line.strip(): continue
            if line.strip() == "exit":
                auto_save(env); break

            tokens = tokenize(line)
            stream = Stream(tokens)
            while stream.peek() is not None:
                ast = read_node(stream)
                if ast is None: break
                result = trampoline(ast, env)
                if result is not None:
                    # StringLiteral: show with repr so it's clear it's a string value
                    # Symbol: show plain (it's an identifier, not a quoted value)
                    # Everything else: default repr
                    if isinstance(result, StringLiteral):
                        print(f"  => {str(result)!r}")
                    elif isinstance(result, Symbol):
                        print(f"  => {result}")
                    else:
                        print(f"  => {result}")

        except EOFError:
            auto_save(env); break
        except KeyboardInterrupt:
            print("\n  (interrupted)")
        except NameError as e:
            print(f"  ! Name Error: {e}")
            if _DEBUG_MODE[0]: traceback.print_exc()
        except TypeError as e:
            print(f"  ! Type Error: {e}")
            if _DEBUG_MODE[0]: traceback.print_exc()
        except SyntaxError as e:
            print(f"  ! Syntax Error: {e}")
            if _DEBUG_MODE[0]: traceback.print_exc()
        except FileNotFoundError as e:
            print(f"  ! I/O Error: {e}")
            if _DEBUG_MODE[0]: traceback.print_exc()
        except PermissionError as e:
            print(f"  ! Capability Error: {e}")
            if _DEBUG_MODE[0]: traceback.print_exc()
        except Exception as e:
            print(f"  ! Error: {e}")
            if _DEBUG_MODE[0]: traceback.print_exc()


if __name__ == "__main__":
    multiline_repl()