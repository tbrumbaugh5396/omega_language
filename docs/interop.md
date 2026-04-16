# Omega Lisp — Python Interop

## Calling Python from Lisp

### `py-eval`

Evaluate a Python expression string and return the result:

```lisp
(py-eval "2 ** 10")          ; => 1024
(py-eval "len([1, 2, 3])")   ; => 3
(py-eval "list(range(5))")   ; => [0, 1, 2, 3, 4]
```

### `py-exec`

Execute a Python statement (no return value):

```lisp
(py-exec "import random")
(py-exec "x = 42")
```

### `getattr`

Access attributes of Python objects:

```lisp
(import "math" m)
(getattr m pi)           ; => 3.141592653589793
((getattr m sqrt) 16)    ; => 4.0
```

### Importing native Python modules

```lisp
(import "math"       m)    ; math module
(import "re"         r)    ; regex
(import "os"         o)    ; os module
(import "json"       j)    ; json
(import "random"     rng)  ; random
```

These become `Module` objects with `origin = "native"`. Access functions via `getattr` or dot notation after `open`:

```lisp
(import "random" rng)
(open rng)
(randint 1 10)   ; works after open
```

---

## Calling Lisp from Python

If you want to call an Omega function from Python, use the transpiler to emit Python:

```lisp
(load "transpiler12.ol")
(define (square x) (* x x))
(transpile-file "square.py" '(square))
```

Then from Python:

```python
import square
print(square.square(5))   # 25
```

---

## Omega Lisp → Python Transpiler

**File:** `transpiler12.ol`

Translates Omega Lisp function definitions to Python source code.

```lisp
(load "transpiler12.ol")

; Define some functions
(define (square x) (* x x))
(define (cube x) (* x x x))
(define (circle-area r) (* 3.14159 (square r)))

; Transpile to Python
(transpile-file "geometry.py" '(square cube circle-area))
```

This writes a complete Python file with a runtime prelude and the three functions.

### What it handles

| Lisp form | Python output |
|-----------|---------------|
| `(define (f x) body)` | `def f(x): return ...` |
| `(lambda (x y) body)` | `lambda x, y: ...` |
| `(if c t f)` | `(t if c else f)` |
| `(cond ...)` | nested ternaries |
| `(let ((x e)) body)` | `(lambda x: body)(e)` |
| `(begin a b c)` | `(a, b, c)[-1]` |
| `(+ - * /)` | `(a + b)` etc. |
| `(eq? a b)` | `(a is b)` |
| `(equal? a b)` | `_structural_equal(a, b)` |
| `(fold f i l)` | `lisp_fold(f, i, l)` |
| `(memoize f)` | `_make_memoized_wrapper(f)` |
| `(module? x)` | `isinstance(x, Module)` |

### Name mangling

Lisp names with `-` and `?` are converted to valid Python identifiers:

| Lisp | Python |
|------|--------|
| `my-fn` | `my_fn` |
| `null?` | `null_p` |
| `list->string` | `list_to_string` |

---

## Python → Omega Lisp Transpiler

**File:** `python_to_lisp4.py`

Converts Python source to Omega Lisp. Useful for understanding Python code in Lisp terms, or for lifting Python utilities into the Lisp ecosystem.

```bash
python3 python_to_lisp4.py myfile.py
# or with output file:
python3 python_to_lisp4.py myfile.py output.ol
```

### From the REPL via py_lift.ol

```lisp
(load "py_lift.ol")

(py->lisp "myfile.py")          ; print annotated Lisp
(py->lisp-clean "myfile.py")    ; print clean Lisp (no confidence scores)
(py-save "myfile.py" "out.ol")  ; lift and write .ol file
(py-stats "myfile.py")          ; lossiness statistics
```

### What it handles

Python → Lisp mapping:

| Python | Lisp |
|--------|------|
| `def f(x): return x` | `(define (f x) x)` |
| `lambda x: x + 1` | `(lambda (x) (+ x 1))` |
| `x if c else y` | `(if c x y)` |
| `for x in xs: body` | `(for-each ...)` |
| `import math` | `(import-native "math" math)` |
| `x = 1` | `(define x 1)` |
| `x += 1` | `(set! x (+ x 1))` |
| `a and b` | `(and a b)` |
| `[x for x in xs if ...]` | `(filter ... (map ...))` |

### Confidence annotations

Output includes confidence scores (`[1.0]` = perfect, `[0.5]` = lossy):

```lisp
; [1.0] def square(x):
(define (square x)
  (* x x))   ; [1.0]

; [0.5] class Foo:    ← classes are lossy
(define Foo None)  ; [class approximation]
```

### Known limitations

- `match/case` (Python 3.10+) — not yet supported
- Walrus operator `:=` — not yet supported
- `async/await` — approximated, marked lossy
- Classes — converted to placeholder defines, lossy

---

## Round-trip: Python → Lisp → Python

```lisp
(load "transpiler12.ol")
(load "py_lift.ol")

(py-roundtrip "myfile.py" "myfile_rt.py")
```

This lifts the Python to Lisp, loads the Lisp definitions, then re-emits Python. Functions using only core forms (`define`, `lambda`, `if`, arithmetic) round-trip cleanly.

---

## Error handling across the boundary

Python exceptions raised during `py-eval` or `py-exec` are caught and re-raised as Lisp errors:

```lisp
(py-eval "1/0")   ; ! Error: division by zero
```

In debug mode you'll see the full Python traceback:

```lisp
(debug-mode true)
(py-eval "1/0")   ; shows full ZeroDivisionError traceback
```
