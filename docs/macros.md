# Omega Lisp — Macro System

## What Macros Are

Macros are transformations on code. Unlike functions — which receive evaluated arguments — macros receive **raw AST** and return a new AST which is then evaluated. This lets you create new control structures, DSLs, and syntactic abstractions.

```lisp
; Define a macro that inverts a condition
(register-macro! 'unless '(test body)
  '(if (not test) body None))

(unless false (print "runs!"))   ; expands to: (if (not false) (print "runs!") None)
```

---

## Registering Macros

```lisp
(register-macro! name params body)
```

- `name` — a symbol (quoted or unquoted)
- `params` — a list of parameter names (quoted or unquoted)
- `body` — the template AST. Use `quasiquote`/`unquote` for most cases.

```lisp
; With quotes (most common — matches (quote ...) syntax)
(register-macro! 'my-when '(test body)
  '(if test body None))

; With quasiquote (needed when you want to splice values)
(register-macro! 'my-and '(a b)
  `(if ,a ,b false))

; Unquoted — identical behaviour, just different surface syntax
(register-macro! my-or (a b)
  `(let ((t ,a)) (if t t ,b)))
```

---

## Quasiquote Templates

Most macro bodies use quasiquote (`` ` ``), unquote (`,`), and unquote-splicing (`,@`).

```lisp
; Build (if cond then else) from a when macro
(register-macro! 'my-when '(cond body)
  `(if ,cond ,body None))

; ,cond and ,body are substituted with the actual call-site arguments
(my-when (> x 0) (print "positive"))
; expands to: (if (> x 0) (print "positive") None)
```

### Splicing lists with `,@`

```lisp
(register-macro! 'my-begin '(forms)
  `(begin ,@forms))
```

---

## Inspecting Expansions

```lisp
(expand '(my-when (> x 0) (print "hi")))
; => (if (> x 0) (print "hi") None)
```

`expand` returns the macro-expanded AST as a data structure, **without evaluating it**. This is the primary debugging tool for macros.

---

## Variable Capture and Hygiene

Omega macros are **not hygienic by default**. A variable name used in the macro body could accidentally shadow a variable in the calling code:

```lisp
(register-macro! 'swap! '(a b)
  `(begin
     (define tmp ,a)
     (set! a ,b)
     (set! b tmp)))

; Works fine normally:
(define x 1) (define y 2) (swap! x y)

; But breaks if the caller also has a variable named 'tmp':
(define tmp 99)
(swap! x y)   ; BUG: 'tmp' in the macro clashes with the caller's 'tmp'
```

### Solution: use `gensym`

```lisp
(define (make-swap-macro)
  (let ((tmp-name (gensym "tmp")))
    (register-macro! 'swap! (list 'a 'b)
      `(begin
         (define ,tmp-name ,a)   ; unique name, won't clash
         (set! a ,b)
         (set! b ,tmp-name)))))
```

`gensym` generates a fresh symbol guaranteed to be unique (`tmp_1_`, `tmp_2_`, etc.).

---

## Nested Macros

Macros can produce calls to other macros, which are expanded recursively:

```lisp
(register-macro! 'my-and2 '(a b)
  `(if ,a ,b false))

(register-macro! 'my-and3 '(a b c)
  `(my-and2 ,a (my-and2 ,b ,c)))

(my-and3 true true true)   ; => true  (expands twice before evaluating)
```

---

## Macros vs Functions: When to Use Each

Use a **macro** when you need to:
- Delay evaluation (like `if`, `and`, `or`)
- Capture variable names from the call site
- Generate code that depends on the syntactic structure of arguments

Use a **function** for everything else. Most things that look like they need macros can be done with higher-order functions.

---

## Built-in Macro-Like Forms

These are special forms, not macros, but they have macro-like behaviour (they don't evaluate all arguments):

| Form | Behaviour |
|------|-----------|
| `if` | Only evaluates the taken branch |
| `define` | Does not evaluate the name |
| `lambda` | Captures body as AST |
| `quote` | Returns argument unevaluated |
| `quasiquote` | Partially evaluates (only `,` and `,@`) |
| `set!` | Does not evaluate the target symbol |
| `memoize!` | Reads symbol name from AST |
