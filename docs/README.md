# Omega Lisp

A minimal, hackable Lisp interpreter written in Python — with macros, modules, tail-call optimization, memoization, and bidirectional Python interop.

```lisp
(define (fib n)
  (if (<= n 1) n
      (+ (fib (- n 1)) (fib (- n 2)))))

(memoize! fib)
(fib 40)   ; => 102334155, instant after warm-up
```

---

## Features

- **Lexical scoping** — closures capture environment references, `set!` mutations are visible through all references
- **Tail-call optimization** — trampoline-based TCO, constant stack for arbitrarily deep recursion
- **Macros** — hygienic-capable via `gensym`, `expand` returns AST for inspection
- **Module system** — `import`, `open`, `with-module`, dotted access `v.fib`, `set!` into modules
- **Memoization** — `memoize`, `memoize!`, `memoize-rec!` for mutual recursion, structural cache keys
- **Python interop** — call Python, import native modules, bidirectional transpilers
- **Clean errors** — readable messages by default, `(debug-mode true)` for full tracebacks

---

## Quick Start

```bash
python3 multiline_repl.py
```

```
Omega Lisp — type 'exit' to quit
λ > (define (square x) (* x x))
λ > (square 5)
  => 25
λ > (map square '(1 2 3 4 5))
  => [1, 4, 9, 16, 25]
```

---

## Running a file

```lisp
(load "examples.ol")
```

Or from the shell:

```bash
python3 multiline_repl.py   # then type (load "examples.ol")
```

---

## Files

| File | Purpose |
|---------------------|--------------------------------------------------------|
| `multiline_repl.py` | The interpreter — parser, evaluator, REPL              |
| `verify.ol`         | Feature verification — run to confirm everything works |
| `examples.ol`       | Core library: math, BST, Maybe/Result, streams         |
| `examples_v2.ol`    | Extended library with explicit `(export ...)`          |
| `transpiler.ol`     | Omega Lisp → Python transpiler                         |
| `python_to_lisp.py` | Python → Omega Lisp transpiler                         |
| `py_lift.ol`        | REPL bridge for the Python→Lisp transpiler             |

---

## Documentation

- [Language Reference](docs/language.md) — evaluation model, types, special forms
- [Macro System](docs/macros.md) — how macros work, quasiquote, gensym
- [Module System](docs/modules.md) — import, dotted access, mutation
- [Memoization](docs/memoization.md) — memoize, memoize!, mutual recursion
- [Python Interop](docs/interop.md) — py-eval, transpilers, round-trip
- [Design Notes](docs/design.md) — trampoline, environment model, decisions

---

## Philosophy

Omega Lisp is designed for **learning and hacking**, not production use. The goal is a language where every semantic decision is visible and debuggable. If you want to understand how Lisps work — environments, closures, TCO, macros — this is a good place to start.

---

## Running Tests

```bash
python3 tests/test_eval.py
python3 tests/test_macros.py
python3 tests/test_modules.py
python3 tests/test_memo.py
python3 tests/test_transpiler.py
```

Or run all at once:

```bash
python3 -m pytest tests/
```
