# Omega Lisp — Language Reference

## Evaluation Model

Omega Lisp uses **lexical scoping** with **mutable bindings**.

- `define` creates a new binding in the current scope
- `set!` mutates an existing binding — the change is visible through all references that share the same environment frame
- Closures capture a *reference* to the environment, not a snapshot of values

```lisp
(define x 10)
(define f (lambda () x))
(set! x 20)
(f)   ; => 20  — f sees the mutation because it holds a reference to the same frame
```

This is standard Scheme/Common Lisp semantics. If you want value capture, copy explicitly:

```lisp
(define x 10)
(let ((captured x))
  (lambda () captured))   ; always returns 10 regardless of later set!
```

---

## Types

| Type | Examples | Notes |
|------|----------|-------|
| Integer | `42`, `-7` | Python int |
| Float | `3.14`, `-0.5` | Python float |
| String | `"hello"` | Printed with quotes |
| Symbol | `x`, `my-fn?` | Identifiers, `-` and `?` allowed |
| Boolean | `true`, `false` | Only `false` is falsy |
| List | `'(1 2 3)` | Python list under the hood |
| None | `None` | Python None — truthy in Omega |
| Lambda | `(lambda (x) x)` | First-class function |
| Module | `(import "m.ol" m)` | Namespace object |

### Truthiness

Only `false` is falsy. Everything else — `0`, `None`, `""`, `'()` — is truthy.

```lisp
(if 0    'yes 'no)   ; => yes
(if None 'yes 'no)   ; => yes
(if '()  'yes 'no)   ; => yes
(if false 'yes 'no)  ; => no
```

### Equality

```lisp
(=       1 1)              ; => true  (numeric equality, also works for symbols)
(eq?     x y)              ; => true if x and y are the same object (identity)
(equal?  '(1 2) '(1 2))    ; => true  (structural deep equality)
(equal?  '(1 2) '(1 3))    ; => false
```

---

## Special Forms

These control evaluation — their arguments are NOT evaluated before the form runs.

### `define`

```lisp
(define x 42)                      ; bind x to 42
(define (square x) (* x x))        ; define function — shorthand for lambda
(define square (lambda (x) (* x x))) ; equivalent
```

### `lambda`

```lisp
(lambda (x y) (+ x y))             ; anonymous function
(lambda (x . rest) ...)             ; variadic: rest collects extra args as list
```

### `if`

```lisp
(if condition then-expr else-expr)
(if condition then-expr)            ; else branch is None
```

### `cond`

```lisp
(cond
  ((< x 0) 'negative)
  ((= x 0) 'zero)
  (else    'positive))
```

### `begin`

```lisp
(begin
  (set! x 1)
  (set! y 2)
  (+ x y))   ; => 3, last value returned
```

### `let`, `let*`, `letrec`

```lisp
(let ((x 1) (y 2)) (+ x y))        ; bindings are parallel (x and y bound at same time)
(let* ((x 1) (y (+ x 1))) y)       ; bindings are sequential (y can see x)
(letrec ((f (lambda (n) (if (= n 0) 1 (* n (f (- n 1))))))) (f 5))  ; mutual recursion
```

### `set!`

```lisp
(set! x 42)          ; mutate local binding
(set! module.x 42)   ; mutate binding inside a module (dotted path)
```

### `quote`

```lisp
'x              ; symbol x as a value
'(1 2 3)        ; list as data, not evaluated
(quote (a b))   ; same as '(a b)
```

### `quasiquote`, `unquote`, `unquote-splicing`

```lisp
`(+ ,x 1)          ; quasiquote: x is evaluated, rest is literal
`(list ,@items)    ; unquote-splicing: splice a list inline
```

---

## Core Primitives

### Arithmetic
```lisp
(+ 1 2 3)    ; => 6   (variadic)
(- 10 3)     ; => 7
(* 2 3 4)    ; => 24  (variadic)
(/ 10 4)     ; => 2.5
(mod 17 5)   ; => 2
(** 2 10)    ; => 1024
```

### Comparison
```lisp
(< 1 2)  (> 2 1)  (<= 1 1)  (>= 2 1)
(= 1 1)  (not= 1 2)
```

### List operations
```lisp
(cons 1 '(2 3))        ; => (1 2 3)
(first '(1 2 3))       ; => 1
(rest  '(1 2 3))       ; => (2 3)
(second '(1 2 3))      ; => 2
(nth '(a b c) 2)       ; => c
(length '(1 2 3))      ; => 3
(append '(1 2) '(3 4)) ; => (1 2 3 4)
(reverse '(1 2 3))     ; => (3 2 1)
(null? '())            ; => true
(list? '(1 2))         ; => true
```

### Higher-order
```lisp
(map (lambda (x) (* x x)) '(1 2 3))       ; => (1 4 9)
(filter (lambda (x) (> x 2)) '(1 2 3 4))  ; => (3 4)
(reduce + '(1 2 3 4 5))                    ; => 15
(fold   + 0 '(1 2 3 4 5))                  ; => 15  (Scheme order: f init lst)
(apply  + '(1 2 3))                        ; => 6
(sort   '(3 1 4 1 5))                      ; => (1 1 3 4 5)
```

### Strings
```lisp
(string-append "hello" " " "world")   ; => "hello world"
(string-length "omega")               ; => 5
(string-upcase "lisp")               ; => "LISP"
(string-split "a,b,c" ",")           ; => ("a" "b" "c")
(number->string 42)                  ; => "42"
(string->number "3.14")              ; => 3.14
```

### I/O
```lisp
(print "hello")        ; prints with newline
(display "hello")      ; prints without newline
(read-file "f.txt")    ; returns file contents as string
(write-file "f.txt" "content")
```

---

## Tail-Call Optimization

Omega uses a trampoline so recursive functions with tail calls run in constant stack space. Any self-call in tail position is optimized automatically — no special syntax needed.

```lisp
(define (loop n)
  (if (= n 0) 0 (loop (- n 1))))

(loop 1000000)   ; => 0, no stack overflow
```

---

## Reader Macros

```lisp
; Register a reader macro for the # character:
(register-reader-macro! '#
  (lambda (stream) (list 'length (read stream))))

# '(a b c)   ; => 3  (expands to (length '(a b c)))
```

---

## Introspection

```lisp
(expand '(my-macro arg))   ; return expanded AST without evaluating
(gensym "prefix")          ; generate a unique symbol
(eval '(+ 1 2))            ; evaluate an expression
(get-source f)             ; return source AST of a Lambda
(memoized? f)              ; true if f has been memoized
(traced? f)                ; true if f has been wrapped by trace-calls
(module? x)                ; true if x is a Module
```

---

## Error Handling

By default, errors show a clean message:

```
  ! Name Error: Unbound symbol: x
  ! Type Error: Not a function: 42
```

Enable full Python tracebacks for debugging:

```lisp
(debug-mode true)    ; show Python tracebacks
(debug-mode false)   ; clean messages only (default)
(debug-mode)         ; query current setting
```
