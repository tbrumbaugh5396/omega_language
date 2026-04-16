# Omega Lisp — Module System

## Importing Modules

```lisp
(import "examples.ol" e)   ; load file, bind as module 'e'
(import "math"        m)   ; import native Python module as 'm'
```

After importing, the module is bound to the alias you provide. The file is executed in an isolated environment — its internal definitions don't leak into your REPL session.

---

## Accessing Module Contents

Use dot notation to access a module's exports:

```lisp
e.square         ; the square function from module e
(e.square 5)     ; call it
e.pi             ; a value
e.MyMath.double  ; nested module access (3-level dot chain)
```

Dot paths can be arbitrarily deep as long as each intermediate value is a Module.

---

## Defining Inline Modules

```lisp
(module MyMath
  (export double triple)          ; explicit export list
  (define (double x) (* 2 x))
  (define (triple x) (* 3 x))
  (define _internal 42))          ; _ prefix: excluded from exports

(MyMath.double 5)    ; => 10
(module? MyMath)     ; => true
```

The `(export ...)` form controls what `module-exports` shows and what `open` brings into scope. Names starting with `_` are always private.

---

## Opening Modules

`open` brings all exports into the current scope:

```lisp
(import "examples.ol" e)
(open e)
(square 9)   ; now directly accessible
```

`with-module` is the scoped version — exports are only available inside the body:

```lisp
(with-module e
  (square 9))   ; => 81

; square is NOT in scope here
```

---

## Mutating Module State

You can set values inside a module using dotted `set!`:

```lisp
(module M
  (export x)
  (define x 10))

M.x            ; => 10
(set! M.x 99)
M.x            ; => 99
```

This is most useful for replacing a module export with a memoized version:

```lisp
(import "verify.ol" v)
(set! v.fib (memoize v.fib))
(memoized? v.fib)   ; => true
```

---

## Module Introspection

```lisp
(module? e)                   ; => true
(module-name e)               ; => "examples.ol"
(module-origin e)             ; => "file" or "native"
(module-exports e)            ; => list of exported names
(module-lookup e 'square)     ; => the square function
```

---

## Export Lists

A flat `.ol` file (no `(module ...)` wrapper) can declare its public API at the top:

```lisp
; mylib.ol
(export square cube pi)   ; only these names are accessible from outside

(define pi 3.14159)
(define (square x) (* x x))
(define (cube x) (* x x x))
(define _helper 0)   ; private
```

Without `(export ...)`, all top-level definitions are exported.

---

## Native Python Modules

```lisp
(import "math" m)
(module-origin m)        ; => "native"
(getattr m pi)           ; => 3.141592653589793
((getattr m sqrt) 144)   ; => 12.0
```

Known standard library modules (`sys`, `re`, `os`, `math`, `json`, `random`, `time`, `collections`, `itertools`, `functools`, etc.) are imported as native modules. Unknown names fall back to file loading.

---

## File Loading vs Importing

| | `load` | `import` |
|-|--------|---------|
| Executes forms | Into current env | Into isolated module env |
| Returns | Last value | Module object |
| Namespace pollution | Yes | No (unless you `open`) |
| Re-load safe | Yes | Yes |
| Use when | Script execution | Library use |
