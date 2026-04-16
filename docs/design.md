# Omega Lisp — Design Notes

## Overview

Omega Lisp is implemented as a single Python file (`multiline_repl27.py`). Every semantic decision is visible in that file. This document explains the key design choices and why they were made.

---

## The Trampoline (TCO)

Python has no tail-call optimization, and its default recursion limit is 1000. To support deep recursion, Omega uses a **trampoline**:

1. When a Lambda call is in tail position, `apply()` returns a `TailCall(expr, env)` object instead of evaluating it
2. The `trampoline()` function loops: if the result is a `TailCall`, evaluate it; otherwise return
3. No Python stack frame is consumed per Lisp tail call

```python
def trampoline(node, env):
    result = eval_node(node, env, set())
    while isinstance(result, TailCall):
        result = eval_node(result.expr, result.env, set())
    return result
```

This gives true O(1) stack depth for tail-recursive Lisp functions.

---

## Environment Model

Environments are Python dicts with a `parent` pointer. Variable lookup walks the chain; mutation uses `find()` to locate the owning frame.

```
REPL env:  {fib: ..., square: ..., x: 20}
    └── module env:  {pi: 3.14, tau: 6.28}
            └── primitives:  {+: ..., map: ..., ...}
```

**Key design decision:** closures capture a *reference* to the environment frame, not a snapshot. This means `set!` mutations are visible through all references:

```lisp
(define x 10)
(define f (lambda () x))
(set! x 20)
(f)   ; => 20
```

This is intentional. It matches Scheme/Common Lisp semantics and enables clean module mutation patterns like `(set! v.fib (memoize v.fib))`.

---

## Memoization and the Closure Problem

The hardest bug in the project's history:

```lisp
(define fib v.fib)
(memoize! fib)
(fib 30)   ; fast
(fib 32)   ; still hung!
```

Why? `v.fib` is a Lambda defined in the module's isolated environment. When `memoize!` rebinds `fib` in the REPL env, the Lambda's body still calls `fib` by looking it up through its **closure chain** — which leads back through the module env, not the REPL env. So it found the original, un-memoized function.

**Fix:** `memoize!` now walks every frame in the closure chain and rebinds any name that points to the same original Lambda:

```python
cursor = f.env
while cursor is not None:
    for k, v in list(cursor.items()):
        if v is f:          # same object
            cursor[k] = wrapper
    cursor = cursor.parent
```

This handles aliases, cross-env captures, and module imports correctly.

---

## Module Isolation

File modules execute in a child of the root primitives env, not the caller's env. This prevents:

1. The caller's definitions leaking into the module
2. The module's definitions polluting the caller

The `opened_modules` list exists to support `open` without causing infinite loops — it's reset to `[]` on each new module env so circular imports can't cause infinite `find()` recursion.

---

## Macro Expansion

Macros are represented as `Macro(params, body, closure_env)` objects. At call time:

1. Raw AST arguments are bound to params in a new env
2. The body is evaluated in that env — this produces the expanded AST
3. The expanded AST is returned as a `TailCall` and evaluated in the calling env

```
(my-inc 5)
    ↓ macro_expand: menv = {x: 5}
    eval (+ x 1) in menv
    ↓ result: ['+', 5, 1]  ← this is the new AST
    ↓ TailCall(['+', 5, 1], calling_env)
    eval → 6
```

For `(expand ...)` (inspection only), pure syntactic substitution is used instead of eval, so the AST is returned without evaluating to a value.

---

## Register-macro! Quoting

`(register-macro! 'name '(params) '(body))` — the quoted forms arrive in the special form handler as `['quote', [...]]`. The handler calls `unwrap_quote()` to strip one level, leaving the actual params list and body AST. It does **not** fully evaluate the body (that would eagerly evaluate the template).

---

## Structural Cache Keys

Memoization uses `_structural_key()` to build hashable keys from arguments. Without this, two list arguments `'(1 2 3)` and `'(1 2 3)` would be different Python objects and map to different cache entries.

```python
def _structural_key(args):
    def to_key(v):
        if isinstance(v, list):
            return ("__list__",) + tuple(to_key(x) for x in v)
        if isinstance(v, (int, float, str, bool, type(None))):
            return v
        return ("__id__", id(v))   # Lambda, Module: use identity
    return tuple(to_key(a) for a in args)
```

---

## Reader Macros

The reader (tokenizer + parser) has a `READ_TABLE` dict mapping characters to handler functions. Reader macros are registered by adding to this table. They fire during parsing, before eval.

The tricky case: if a file registers a reader macro (like `~`), then you `load` the same file again, the `~` macro fires during re-parsing and corrupts the source. Fix: the `load` handler snapshots and removes user-registered reader macros before parsing, then restores them.

---

## The `expand` Special Form

`expand` needed its own special form (not just `expand_all`) because:

1. `expand_all` calls `macro_expand` which evaluates the body — this gives the value, not the AST
2. For inspection, we want the substituted template before evaluation

The special form does pure substitution: it finds the param→arg mapping, walks `macro.body`, and replaces symbols. For quasiquote bodies it evaluates the quasiquote (to resolve `` `,`` unquotes) then substitutes.

---

## Debug Mode

A module-level mutable list `_DEBUG_MODE = [False]` acts as a toggle. The REPL error handlers check `_DEBUG_MODE[0]` to decide whether to print Python tracebacks. Using a list (not a plain bool) avoids Python's global variable mutation rules — closures can read and write `_DEBUG_MODE[0]` without `global` declarations.
