# Omega Lisp — Memoization

## The Problem

Naive recursive functions with overlapping subproblems recompute the same values exponentially:

```lisp
(define (fib n)
  (if (<= n 1) n
      (+ (fib (- n 1)) (fib (- n 2)))))

(fib 35)   ; takes several seconds — O(2^n) calls
```

Memoization caches results so each unique input is computed only once.

---

## `memoize` — Non-mutating wrapper

Returns a new function with a result cache. The original is unchanged.

```lisp
(define memo-fib (memoize fib))
(memo-fib 30)   ; 0.004s first call
(memo-fib 30)   ; instant — from cache
```

**Important:** `memoize` alone doesn't help self-recursive functions because the internal recursive calls still go to the original `fib`, not `memo-fib`. Use `memoize!` for that.

---

## `memoize!` — In-place memoization

Replaces the named function in its environment with a memoized version. Because the name is rebound before any recursive call, all internal calls also hit the cache.

```lisp
(define (fib n)
  (if (<= n 1) n
      (+ (fib (- n 1)) (fib (- n 2)))))

(memoize! fib)          ; quoted or unquoted both work
; or: (memoize! 'fib)

(fib 30)   ; 0.004s — fills cache
(fib 31)   ; instant — fib(31) = fib(30) + fib(29), both cached
(fib 32)   ; instant — same reason
(fib 40)   ; instant — cache grows linearly
```

### Why `memoize!` works where `memoize` doesn't

`memoize!` rebinds the symbol in every frame in the closure chain. This means when the body of `fib` calls `fib`, it finds the memoized wrapper — not the original.

### Works with aliases too

```lisp
(define (fib n) ...)
(define fibcopy fib)
(memoize! fibcopy)   ; also rebinds 'fib' since they point to the same Lambda
```

---

## `memoize-rec!` — Mutual recursion

For mutually-recursive functions, `memoize!` on just one is not enough — the other still calls the original. `memoize-rec!` atomically installs wrappers for all functions in the group before any of them are called:

```lisp
(define (even? n) (if (= n 0) true  (odd?  (- n 1))))
(define (odd?  n) (if (= n 0) false (even? (- n 1))))

(memoize-rec! '(even? odd?))

(even? 40)   ; fast — both sides cache each other's results
```

---

## Cache management

```lisp
(memoized? f)        ; => true if f was memoized
(memo-clear! f)      ; empty the cache (forces recomputation on next call)
(memo-stats f)       ; => [cache-size, 0]  (hit tracking future work)
```

---

## Structural cache keys

Cache keys are built using structural equality, not Python object identity. This means two lists with the same elements map to the same cache entry:

```lisp
(define memo-sum (memoize list-sum))
(memo-sum '(1 2 3))   ; computes, caches under key ((1 2 3))
(memo-sum '(1 2 3))   ; cache hit — even though it's a different list object
```

---

## Memoization and purity

Memoization is only correct for **pure functions** — functions whose output depends only on their inputs and which have no side effects.

Do **not** memoize:
- `print`, `display` — side effects
- `random`, `time` — non-deterministic
- Functions that mutate shared state

---

## Comparison with TCO

| | Memoization | Tail-call optimization |
|-|-------------|----------------------|
| Fixes | Repeated recomputation (overlapping subproblems) | Stack overflow (deep recursion) |
| Best for | Fibonacci-style trees | Linear recursion like `loop` |
| Required shape | Any recursive function | Tail-position calls only |
| Overhead | Memory for cache | None — same speed |

For `fib`, memoization is the right tool. For `factorial` or `loop`, TCO is the right tool. Often you want both.

---

## Tracing calls

Use `trace-calls` to observe the call pattern before and after memoization:

```lisp
(define (fib n)
  (if (<= n 1) n (+ (fib (- n 1)) (fib (- n 2)))))

; Before memoization — exponential calls
(define tfib (trace-calls fib))
(tfib 5)
; → (fib 5)
;   → (fib 4)
;     → (fib 3)
;       → (fib 2)
;         → (fib 1) ...  ; many repeated calls

(memoize! fib)

; After — each n called once
(tfib 6)
; → (fib 6)   ; only 1 new call, fib(5) already cached
```
