# Omega Lisp — Complete Reference

> **Interpreter**: `multiline_repl31.py`  
> **Standard library**: `types.ol`, `effects.ol`, `std.ol`  
> **Tools**: `transpiler12.ol`, `py_lift.ol`, `html_weather.ol`  
> **Companion**: `python_to_lisp4.py`

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Core Language](#core-language)
3. [Types Library](#types-library)
4. [Effects Library](#effects-library)
5. [Standard Library](#standard-library)
6. [Continuations & Generators](#continuations--generators)
7. [Python Bridge](#python-bridge)
8. [Transpiler](#transpiler)
9. [Python Lifter](#python-lifter)
10. [HTML Generation](#html-generation)
11. [Important Gotchas](#important-gotchas)

---

## Quick Start

```bash
python3 multiline_repl31.py
```

```lisp
; In the REPL
(load "effects.ol")          ; loads types.ol + effects system
(load "std.ol")              ; loads string/list/math utilities

(define (square x) (* x x))
(square 5)                   ; => 25

(run-state 0
  (lambda ()
    (put-state (+ (get-state) 1))
    (get-state)))            ; => (Pair 1 1)
```

---

## Core Language

### Defining Things

```lisp
(define x 42)                        ; value binding
(define (square x) (* x x))          ; function shorthand
(define square (lambda (x) (* x x))) ; lambda longhand
(define (variadic . args) args)       ; variadic: args is a list
(define (head-rest first . rest) ...) ; dotted: named head + rest list
```

### Control Flow

```lisp
(if condition then-expr else-expr)

(cond
  ((= x 1) "one")
  ((= x 2) "two")
  (else    "other"))

(when condition body...)              ; like (if cond (begin body...) '())
(unless condition body...)
```

### Let Forms

```lisp
(let ((x 1) (y 2)) (+ x y))          ; parallel bindings
(let* ((x 1) (y (* x 2))) y)         ; sequential bindings
(letrec ((f (lambda (n) ...))) ...)   ; recursive bindings
```

### Sequencing

```lisp
(begin expr1 expr2 ... exprN)         ; returns exprN
```

### Lists

```lisp
(list 1 2 3)           ; => (1 2 3)
'(1 2 3)               ; quoted list
(cons 0 '(1 2 3))      ; => (0 1 2 3)
(first '(1 2 3))       ; => 1  (same as car)
(rest  '(1 2 3))       ; => (2 3)  (same as cdr)
(second '(1 2 3))      ; => 2
(nth '(1 2 3) 2)       ; => 3  (0-indexed)
(length '(1 2 3))      ; => 3
(append '(1 2) '(3 4)) ; => (1 2 3 4)
(reverse '(1 2 3))     ; => (3 2 1)
(map f lst)
(filter pred lst)
(fold f init lst)       ; left fold: (fold + 0 '(1 2 3)) => 6
(for-each f lst)        ; side-effects only
(in x lst)              ; membership test, returns bool
```

### Predicates

```lisp
(null? '())    ; true for empty list
(list? x)
(number? x)    (integer? x)    (string? x)
(symbol? x)    (bool? x)       (lambda? x)
(equal? a b)   ; deep structural equality
(eq? a b)      ; identity equality
```

### Strings

```lisp
(string-append "hello" " " "world")   ; => "hello world"
(string-length "abc")                 ; => 3
(string-split "a,b,c" ",")            ; => ("a" "b" "c")
(string-contains "hello" "ell")       ; => true
(substring "hello" 1 3)              ; => "el"
(number->string 42)                   ; => "42"
(string->number "42")                 ; => 42
(symbol->string 'foo)                 ; => "foo"
(string->symbol "foo")                ; => foo
```

### Arithmetic & Comparison

```lisp
(+ - * /)    (mod x y)    (expt x y)
(< > <= >= = !=)
(abs x)  (floor x)  (ceiling x)  (round x)  (sqrt x)
(min a b)  (max a b)
```

### I/O

```lisp
(print x)        ; prints with newline
(display x)      ; prints without newline
(newline)
(read-line)      ; reads a line from stdin
```

### Modules

```lisp
(module MyMod
  (export fn1 fn2)
  (define (fn1 x) ...))
(open MyMod)           ; bring exports into scope

(module-exports MyMod) ; => list of exported names
(module-lookup MyMod 'fn1) ; => fn1's value
```

---

## Types Library

**Load**: `(load "types.ol")` — also loaded automatically by `effects.ol`

### define-type

```lisp
(define-type Shape
  (Circle radius)
  (Rect   width height))

(Circle 5)              ; => ('Circle 5)
(tag-of (Circle 5))     ; => 'Circle
(tag= (Circle 5) 'Circle) ; => true
(second (Circle 5))     ; => 5  (radius)
```

### Option

```lisp
(Some 42)               ; => ('Some 42)
(None)                  ; => ('None)   — NOTE: call it, don't use bare None

(some? (Some 42))       ; => true
(none? (None))          ; => true
(option-get (Some 42) 0)        ; => 42  (default 0 if None)
(option-map f (Some 5))         ; => (Some (f 5))
(option-map f (None))           ; => (None)
(option-bind (Some 5) (lambda (x) (Some (* x x))))  ; => (Some 25)
(option-or (None) (Some 99))    ; => (Some 99)
```

### Result

```lisp
(Ok  42)                ; => ('Ok  42)
(Err "oops")            ; => ('Err "oops")

(ok?  (Ok 42))          ; => true
(err? (Err "x"))        ; => true
(result-get (Ok 42) 0)           ; => 42
(result-map f (Ok 5))            ; => (Ok (f 5))
(result-map f (Err "e"))         ; => (Err "e")
(result-bind (Ok 5) (lambda (x) (Ok (* x x))))  ; => (Ok 25)
```

### Either

```lisp
(Left  1)   (Right 2)
(left? x)   (right? x)
(either-map f g either-val)       ; apply f to Left value, g to Right value
```

### Pair

```lisp
(Pair 1 2)
(pair-first  (Pair 1 2))    ; => 1
(pair-second (Pair 1 2))    ; => 2
(pair-map f g pair-val)     ; apply f to first, g to second
```

### Lazy Streams

```lisp
(stream-from 1)                      ; 1, 2, 3, ... (infinite)
(stream-repeat 7)                    ; 7, 7, 7, ...
(stream-iterate (lambda (x) (* x 2)) 1)  ; 1, 2, 4, 8, ...
(list->stream '(10 20 30))           ; finite stream from list
(stream-take 5 (stream-from 1))      ; => (1 2 3 4 5)
(stream-map    f stream)
(stream-filter pred stream)
(stream-fold   f init n stream)      ; fold first n elements
(stream-drop   n stream)
(stream-zip    s1 s2)
(stream-flatten stream-of-streams)
```

### Function Utilities

```lisp
(compose f g)       ; (compose f g)(x) = (f (g x))
(identity x)        ; x
(flip f)            ; (flip f)(a b) = (f b a)
(const x)           ; (const x)(y) = x
```

---

## Effects Library

**Load**: `(load "effects.ol")` — also loads types.ol

> **Important**: `None` in Omega Lisp (after loading types.ol) is a zero-arg ADT constructor — it evaluates to a Lambda, NOT to Python's None. Use `'()` as the unit/void sentinel value. Use `(null? x)` to check for it.

### Core API

```lisp
(perform effect arg1 arg2 ...)   ; fire an effect
(handle handlers thunk)          ; install handlers for thunk's duration
(on effect handler-fn)           ; create a handler clause
(with-handler (on Eff fn) body)  ; shorthand for single handler

; handler-fn signature: (lambda (arg1 arg2 ... k) ...)
; where k is the resumption continuation: (k return-value)
```

### State

```lisp
(run-state initial-value thunk)   ; => (Pair final-val final-state)
(get-state)                       ; read current state
(put-state new-val)               ; replace state
(modify-state f)                  ; update state with function

(run-state 0
  (lambda ()
    (put-state 10)
    (modify-state (lambda (s) (+ s 5)))
    (get-state)))    ; => (Pair 15 15)
```

### Reader

```lisp
(run-reader env-value thunk)      ; run thunk with read-only env
(ask)                             ; read the current environment value

(run-reader '(host "localhost" port 8080)
  (lambda ()
    (second (ask))))              ; => "localhost"
```

### Writer

```lisp
(run-writer thunk)                ; => (Pair return-val log-list)
(tell x)                         ; append x to the log

(run-writer
  (lambda ()
    (tell "step1")
    (tell "step2")
    42))                          ; => (Pair 42 ("step1" "step2"))
```

### Exception

```lisp
(run-exception thunk)             ; => (Ok val) or (Err msg)
(throw-exc message)               ; raise an exception
(catch-exc thunk handler-fn)      ; run thunk, call handler on throw

(catch-exc
  (lambda () (/ 10 0))
  (lambda (e) (string-append "caught: " e)))
```

### IO

```lisp
(run-io thunk)
(io-print message)
(io-read  prompt)
```

### Custom Effects

```lisp
(define Tick (make-effect 'Tick))

(run-state 0
  (lambda ()
    (handle
      (list (on Tick (lambda (k) (put-state (+ (get-state) 1)) (k '()))))
      (lambda ()
        (perform Tick)
        (perform Tick)
        (perform Tick)
        (get-state)))))    ; => (Pair 3 3)
```

### Nesting Effects

Effects compose correctly when handlers are nested. State inside a Tick handler (as above) works. Exception + Writer:

```lisp
(run-exception
  (lambda ()
    (run-writer
      (lambda ()
        (tell "before")
        (throw-exc "stop")
        (tell "after")))))   ; => (Err "stop")
```

> **Known limitation**: Reader-wrapping-Writer with `ask` inside `tell`'s argument does not fully compose in the current shift/reset implementation. Use `let` to resolve the ask value first:
> ```lisp
> ; Instead of: (tell (ask))
> ; Use:        (let ((v (ask))) (tell v))
> ```

---

## Standard Library

**Load**: `(load "std.ol")` — loads types.ol + effects.ol

### String Utilities

```lisp
(str-join sep lst)              ; (str-join ", " '("a" "b")) => "a, b"
(str-split str sep)             ; (str-split "a,b" ",") => ("a" "b")
(str-trim str)                  ; strip leading/trailing whitespace
(str-pad-left  str width char)  ; right-align
(str-pad-right str width char)  ; left-align
(str-repeat str n)              ; (str-repeat "-" 3) => "---"
(str-contains? str sub)         ; alias for string-contains
```

### List Utilities

```lisp
(list-last lst)
(list-init lst)                 ; all but last
(list-flatten lst)              ; deep flatten
(list-zip l1 l2)                ; zip two lists
(list-unzip pairs)              ; split list of pairs
(list-group-by key-fn lst)      ; alist keyed by (key-fn item)
(list-partition pred lst)       ; => (Pair passing failing)
(list-range start end)          ; (list-range 1 5) => (1 2 3 4)
(list-take n lst)
(list-drop n lst)
(list-take-while pred lst)
(list-drop-while pred lst)
(list-any pred lst)
(list-all pred lst)
(list-find pred lst)            ; => (Some x) or (None)
(list-find-index pred lst)      ; => (Some i) or (None)
(list-sum lst)
(list-product lst)
(list-min lst)  (list-max lst)  (list-mean lst)
(list-unique lst)               ; remove duplicates (preserves order)
(list-count pred lst)
(list-intersect l1 l2)
(list-union l1 l2)
(list-diff l1 l2)
```

### Math

```lisp
(square x)   (cube x)
(clamp lo hi x)             ; (clamp 0 10 15) => 10
(lerp t a b)                ; linear interpolation
(sign x)                    ; -1, 0, or 1
```

### Function Utilities

```lisp
(pipe x f1 f2 f3)           ; (pipe x f1 f2) = (f2 (f1 x))
(thread-first x forms)      ; thread x as first arg through forms
(thread-last  x forms)      ; thread x as last arg through forms
(memoize-fn f)              ; memoize a function
(negate pred)               ; (negate null?) => (lambda (x) (not (null? x)))
(both? p1 p2)               ; (both? number? integer?)
(either? p1 p2)
```

### Association Lists (alists)

```lisp
(alist-get  key alist default)      ; lookup with default
(alist-set  key val alist)          ; returns new alist with key=val
(alist-has? key alist)
(alist-keys alist)
(alist-vals alist)
(alist-map  f alist)                ; apply f to each (key . val)
```

### Debug

```lisp
(debug-print label val)    ; prints "label: val", returns val
(trace-val label val)      ; same — useful inline
```

---

## Continuations & Generators

### shift / reset

```lisp
(reset body)                    ; establishes a reset boundary
(shift k body)                  ; captures continuation into k, evaluates body
(multi-shot! k)                 ; make a one-shot continuation reusable
```

### Generator Pattern

```lisp
; Use '() as the null sentinel (null? returns true for it)
(define (make-range n)
  (define resume '())      ; '() = uninitialized
  (define done   false)
  (define (next)
    (if done
        'done
        (if (null? resume)
            ; First call: enter the coroutine
            (reset
              (letrec ((loop (lambda (i)
                (if (< i n)
                    (begin
                      (shift k
                        (begin (set! resume (multi-shot! k)) i))
                      (loop (+ i 1)))
                    (begin (set! done true) 'done)))))
                (loop 0)))
            ; Subsequent calls: resume
            (resume '()))))
  next)

(define g (make-range 3))
(g)   ; => 0
(g)   ; => 1
(g)   ; => 2
(g)   ; => 'done
```

> **Note**: Always initialize `resume` to `'()` and check `(null? resume)`. Do NOT use bare `None` — after loading `types.ol`, `None` is an ADT constructor (a Lambda), not null.

---

## Python Bridge

### py-exec / py-eval

```lisp
(py-exec "import datetime")
(py-exec "x = 42")
(py-eval "x + 1")            ; => 43
(py-eval "datetime.date.today().isoformat()")

; Longer Python via multiline string
(py-exec "
def fib(n):
    a, b = 0, 1
    for _ in range(n): a, b = b, a+b
    return a
")
(py-eval "fib(10)")          ; => 55
```

### Calling Python Libraries

```lisp
(py-exec "import json")
(py-eval "json.dumps({'a': 1, 'b': [2, 3]})")
; => "{\"a\": 1, \"b\": [2, 3]}"

(py-exec "import requests")
(py-eval "requests.get('https://api.example.com').json()")
```

### write-file / read-file

```lisp
(write-file "output.txt" "hello world")
(read-file  "output.txt")   ; => "hello world"
```

### Defined? (new in repl31)

```lisp
(defined? 'some-name)        ; => true if bound in current env, false otherwise
(defined? 'transpile-file)   ; => false before loading transpiler12.ol
```

---

## Transpiler

**Load**: `(load "transpiler12.ol")`

Compiles Omega Lisp functions to Python source code with a self-contained runtime prelude.

### Basic Usage

```lisp
(load "transpiler12.ol")

(define (square x) (* x x))
(define (cube   x) (* x x x))
(define (add a b)  (+ a b))

; Transpile specific functions to a .py file
(transpile-file "math_funcs.py" '(square cube add))

; Transpile a single function
(transpile-file "square.py" 'square)

; Get Python source as a string
(transpile-module '(square cube))
```

### Generated Output

`math_funcs.py` will contain the Omega Runtime Prelude (helper classes/functions) followed by the transpiled definitions:

```python
# ── Omega Runtime Prelude ────────────────────────────────────────────────
class Symbol(str): ...
def first(x): ...
# ... more helpers ...

# ── Transpiled functions ─────────────────────────────────────────────────

def square(x):
    return (x * x)

def cube(x):
    return ((x * x) * x)

def add(a, b):
    return (a + b)
```

```bash
python3 -c "import math_funcs; print(math_funcs.square(5))"   # => 25
```

### Name Mangling

Omega names are mangled to valid Python identifiers:

| Omega    | Python       |
|----------|-------------|
| `square` | `square`     |
| `is-ok?` | `is_ok_p`    |
| `->str`  | `_to_str`    |
| `*args*` | `_args_`     |

### Supported Forms

`define`, `lambda`, `if`, `cond`, `let`/`let*`/`letrec`, `begin`, `quote`, arithmetic/comparison operators, `not`, `null?`, `number?`/`integer?`/`string?`/`symbol?`/`list?`/`bool?`/`lambda?`, `eq?`, `equal?`, `fold`, `memoize`, `memoized?`, `trace-calls`, `traced?`, `module?`, `module-name`, `module-origin`, `module-exports`, `module-lookup`.

### What Doesn't Transpile

Effects (`perform`, `handle`, `shift`, `reset`), `py-exec`/`py-eval`, macros, `load`, `module`/`open`. For those, use them in the Omega REPL environment and only transpile the pure functional parts.

---

## Python Lifter

**Load**: `(load "py_lift.ol")`  
**Requires**: `python_to_lisp4.py` in the working directory

Converts Python source files to Omega Lisp. Handles functions, classes (partially), conditionals, loops (partially converted to recursion).

### Usage

```lisp
(load "py_lift.ol")

; Print annotated Lisp (with confidence scores)
(py->lisp "myfile.py")

; Print clean Lisp (no annotations)
(py->lisp-clean "myfile.py")

; Return lifted source as a string
(define lisp-src (py-ast "myfile.py"))

; Save annotated .ol file
(py-save "myfile.py" "myfile.ol")

; Save clean .ol file
(py-save-clean "myfile.py" "myfile_clean.ol")

; Get lossiness statistics
(py-stats "myfile.py")
; => "{'total_annotated': 15, 'lossy_nodes': 2, 'min_confidence': 0.5, 'lossiness_pct': 13.3}"
```

### Full Round-trip (Python → Lisp → Python)

```lisp
(load "transpiler12.ol")   ; load transpiler first
(load "py_lift.ol")

(py-roundtrip "input.py" "output.py")
; Writes input.py.roundtrip.ol (Lisp) and output.py (Python)
```

### Confidence Annotations

The annotated output marks each node with a confidence score (0.0–1.0):

```lisp
; With annotations:
(__meta__ {:confidence 1.0 :source "python"} (define (square x) (* x x)))

; Lossy node example:
(__meta__ {:confidence 0.5 :lossy true :reason "for-loop approximated"}
  (python-opaque ForStatement))
```

### What Lifts Well

- Pure functions: **100% confidence, 0% lossy**
- Simple classes: partial (methods become functions, class body becomes module)
- Comprehensions: converted to `map`/`filter`
- Try/except: converted to `catch-exc`

### What Lifts Poorly

- `async`/`await`, generators, decorators, global/nonlocal statements
- Complex inheritance hierarchies
- Walrus operator (`:=`)

---

## HTML Generation

**Load**: `(load "html_weather.ol")`

Generates weather dashboard HTML pages using a semantic Lisp DSL.

### Usage

```lisp
(load "html_weather.ol")

; Generate default 6-city page
(save-modern-page "weather.html")

; Custom city list
(save-weather-page "forecast.html"
  (list
    (list "London"    "15°C"  "Partly Cloudy")
    (list "Paris"     "18°C"  "Sunny")
    (list "New York"  "12°C"  "Windy")))
```

### How py-write Works

Uses triple-quoted Python strings so CSS with single-quoted font families (`font-family: 'Segoe UI'`) and HTML with `style='...'` attributes all work safely:

```lisp
(define (py-write str)
  (py-exec (string-append "f.write('''" str "''')")))
```

The only unsafe input would be a literal `'''` in the HTML content — which never occurs in practice.

### Building Custom Pages

```lisp
; Open the file
(py-exec "f = open('page.html', 'w', encoding='utf-8')")

; Use the DSL components
(theme-open)
(ui-header "My App" "subtitle here")
(ui-weather-card "London" "15°C" "Partly Cloudy")
(ui-grid-close)
(ui-footer)
(theme-close)

(py-exec "f.close()")
```

---

## Important Gotchas

### 1. None vs '() vs (None)

After loading `types.ol`, these are three different things:

| Expression | Value | Use for |
|-----------|-------|---------|
| `None` (bare) | `<Lambda ()>` — the None ADT *constructor* | never use as a value |
| `(None)` | `['None']` — an Option None *instance* | "no value" in Option context |
| `'()` | `[]` — the empty list | unit/void return, null sentinel |

```lisp
(null? None)    ; => false  (None is a Lambda)
(null? (None))  ; => false  (None is an ADT tag)
(null? '())     ; => true   ← use this
```

**Rule**: use `'()` where you mean "nothing" / unit. Use `(None)` only for the Option type.

### 2. define Inside Functions

`(define x val)` inside a function body defines `x` at **module level**, not locally. This means:

```lisp
(define (make-counter)
  (define count 0)       ; module-level!
  (define (inc!) (set! count (+ count 1)) count)
  inc!)

; All counters made by make-counter share the same `count`
```

Use `let` for true local variables:

```lisp
(define (make-counter)
  (let ((count 0))
    (lambda () (set! count (+ count 1)) count)))
```

### 3. Generator Initialization

Generators must use `'()` as the uninitialized sentinel, not `None`:

```lisp
; WRONG — None is a Lambda, not null
(define resume None)
(if (null? resume) ...)   ; always false

; CORRECT
(define resume '())
(if (null? resume) ...)   ; true on first call
```

### 4. Effects Unit Value

Use `'()` as the return value from effect handlers that return "nothing":

```lisp
; CORRECT
(on State (lambda (op s k) (set! cell s) (k '())))

; WRONG — (k None) passes the Lambda constructor as the continuation value
(on State (lambda (op s k) (set! cell s) (k None)))
```

### 5. R+W Effect Composition

Reader-wrapping-Writer works when `ask` is used as a standalone expression, but **not** when `ask` fires inside another function's argument position:

```lisp
; WORKS
(run-reader 10
  (lambda ()
    (run-writer
      (lambda ()
        (let ((v (ask)))       ; resolve ask first
          (tell v)
          (tell (* 2 v))
          v)))))

; BROKEN — ask inside tell's arg
(run-reader 10
  (lambda ()
    (run-writer
      (lambda ()
        (tell (ask))           ; ask fires inside tell arg — not supported
        '()))))
```

### 6. Multi-Expression Strings in ev

When using the Python `ev()` helper with multi-expression Lisp strings, the parser only reads the **first** form. Wrap in `begin`:

```lisp
; Multiple top-level forms need begin wrapper
(begin
  (define (f x) (* x x))
  (define (g x) (+ x 1))
  (f (g 3)))              ; => 16
```

### 7. py-write Safety

`py-write` uses `f.write('''...''')` — safe for all HTML/CSS. The only dangerous input is content containing `'''` literally, which never appears in HTML. Do NOT use the old `f.write("...")` style — it breaks on CSS font stacks with single quotes.
