; =============================================================================
; test.ol — Omega Lisp kernel stress tests
; Run: (load "test.ol")
; Covers: deep recursion, memoization, macros, quasiquote splicing, modules
; =============================================================================


; ---------------------------------------------------------------------------
; 1. DEEP RECURSION
; ---------------------------------------------------------------------------

(define (count-down n)
  (if (= n 0) 'lift-off
      (count-down (- n 1))))

(count-down 10)      ; => lift-off
(count-down 100)     ; => lift-off
(count-down 1000)    ; => lift-off
(count-down 10000)   ; => lift-off


; ---------------------------------------------------------------------------
; 2. TAIL-RECURSIVE FIBONACCI (large-number check)
; ---------------------------------------------------------------------------

(define (fib n)
  (define (go n a b)
    (if (= n 0) a (go (- n 1) b (+ a b))))
  (go n 0 1))

(fib 10)    ; => 55
(fib 30)    ; => 832040
(fib 50)    ; => 12586269025
(fib 70)    ; => 190392490709135


; ---------------------------------------------------------------------------
; 3. MEMOIZATION
; ---------------------------------------------------------------------------

(define (slow-fib n)
  (if (<= n 1) n
      (+ (slow-fib (- n 1)) (slow-fib (- n 2)))))

(define fast-fib (memoize slow-fib))

(fast-fib 10)           ; => 55
(fast-fib 10)           ; => 55   (from cache)
(fast-fib 20)           ; => 6765

(memoized? fast-fib)    ; => true
(memoized? slow-fib)    ; => false

(memo-clear! fast-fib)
(fast-fib 10)           ; => 55   (recomputed from scratch)

; In-place memoization — recursive calls also hit the cache
(define (rec-fib n)
  (if (<= n 1) n
      (+ (rec-fib (- n 1)) (rec-fib (- n 2)))))

(memoize! 'rec-fib)
(rec-fib 30)    ; => 832040
(rec-fib 35)    ; => 9227465


; ---------------------------------------------------------------------------
; 4. QUASIQUOTE AND SPLICING
; ---------------------------------------------------------------------------

(define part1 '(1 2))
(define part2 '(3 4))

`(Head ,@part1 Middle ,@part2 Tail)    ; => [Head, 1, 2, Middle, 3, 4, Tail]
`(a ,(+ 1 2) b)                        ; => [a, 3, b]
`(,@part1 ,@part2)                     ; => [1, 2, 3, 4]
`(nested (,@part1) (,@part2))          ; => [nested, [1, 2], [3, 4]]


; ---------------------------------------------------------------------------
; 5. REGISTER-MACRO! — user-defined macros
; ---------------------------------------------------------------------------

; unless: run body only when condition is false
(register-macro! unless (__cond__ . __body__)
  `(if (not ,__cond__) (begin ,@__body__) '()))

(unless false 42)              ; => 42
(unless true  42)              ; => ()
(unless (= 1 2) "not equal")  ; => "not equal"
(unless (= 1 1) "equal")      ; => ()

; swap! macro: exchange two bindings
(register-macro! swap! (a b)
  `(let ((tmp ,a)) (set! ,a ,b) (set! ,b tmp)))

(define x 10)
(define y 20)
(swap! x y)
x    ; => 20
y    ; => 10


; ---------------------------------------------------------------------------
; 6. MODULE SYSTEM
; ---------------------------------------------------------------------------

(module Shapes
  (export circle-area rect-area triangle-area)
  (define pi 3.141592653589793)
  (define (circle-area r)   (* pi r r))
  (define (rect-area w h)   (* w h))
  (define (triangle-area b height) (* 0.5 b height))
  (define _pi-approx 3.14159)   ; private
)

(module? Shapes)                ; => true
(module-exports Shapes)         ; => ["circle-area", "rect-area", "triangle-area"]
(Shapes.circle-area 1)          ; => 3.141592653589793
(Shapes.rect-area 3 4)          ; => 12
(Shapes.triangle-area 6 8)      ; => 24.0

; with-module: scoped open — names available only inside body
(with-module Shapes
  (rect-area 5 6))              ; => 30

; open: bring all exports into scope permanently
(open Shapes)
(circle-area 2)                 ; => 12.566370614359172
(rect-area 10 10)               ; => 100


; ---------------------------------------------------------------------------
; 7. NESTED MODULES AND DOT ACCESS
; ---------------------------------------------------------------------------

(module Math
  (export square cube power)
  (define (square x) (* x x))
  (define (cube x)   (* x x x))
  (define (power b e)
    (define (go e acc)
      (if (= e 0) acc (go (- e 1) (* acc b))))
    (go e 1))
)

(Math.square 7)         ; => 49
(Math.cube 3)           ; => 27
(Math.power 2 10)       ; => 1024
(Math.power 3 5)        ; => 243


; ---------------------------------------------------------------------------
; 8. LARGE STRUCTURAL OPERATIONS
; ---------------------------------------------------------------------------

; Build and query a "type-record" as a tagged list
(define (make-record type-name fields)
  (list 'record type-name fields))

(define (record-type r)   (second r))
(define (record-fields r) (third r))

(define (has-field? record field-name)
  (in field-name (record-fields record)))

(define mega-record
  (make-record "MegaType"
    '(m1 m2 m3 m4 m5 m6 m7 m8 m9 m10)))

(record-type mega-record)                ; => "MegaType"
(length (record-fields mega-record))     ; => 10
(has-field? mega-record 'm10)            ; => true
(has-field? mega-record 'missing)        ; => false


; ---------------------------------------------------------------------------
; 9. PREDICATE COMPOSITION (replacing refinement chaining)
; ---------------------------------------------------------------------------

(define (make-predicate . preds)
  (lambda (x) (fold (lambda (ok p) (and ok (p x))) true preds)))

(define even?     (lambda (x) (= (mod x 2) 0)))
(define positive? (lambda (x) (> x 0)))
(define large?    (lambda (x) (> x 10)))

(define pos-even-large? (make-predicate even? positive? large?))

(pos-even-large? 12)    ; => true
(pos-even-large? -2)    ; => false
(pos-even-large? 7)     ; => false
(pos-even-large? 4)     ; => false
(pos-even-large? 100)   ; => true
