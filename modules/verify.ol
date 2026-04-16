; =============================================================================
; verify.ol — Omega Lisp feature verification
; Run: (load "verify.ol")   or   (import "verify.ol" v)
; =============================================================================


; ---------------------------------------------------------------------------
; 1. BASICS
; ---------------------------------------------------------------------------

(define (square x) (* x x))
(define (cube x) (* x x x))

(square 7)                              ; => 49
(cube 3)                                ; => 27
(+ 1 2 3 4 5)                           ; => 15
(string-append "hello" " " "world")     ; => "hello world"
(map square '(1 2 3 4 5))              ; => [1, 4, 9, 16, 25]


; ---------------------------------------------------------------------------
; 2. TAIL-RECURSIVE FUNCTIONS
; ---------------------------------------------------------------------------

(define (fib n)
  (define (go n a b)
    (if (= n 0) a (go (- n 1) b (+ a b))))
  (go n 0 1))

(fib 10)    ; => 55
(fib 30)    ; => 832040
(fib 50)    ; => 12586269025

(define (factorial n)
  (define (go n acc)
    (if (= n 0) acc (go (- n 1) (* acc n))))
  (go n 1))

(factorial 10)   ; => 3628800
(factorial 20)   ; => 2432902008176640000


; ---------------------------------------------------------------------------
; 3. HIGHER-ORDER FUNCTIONS
; ---------------------------------------------------------------------------

(filter (lambda (x) (= (mod x 2) 0)) '(1 2 3 4 5 6))   ; => [2, 4, 6]
(reduce + '(1 2 3 4 5))                                  ; => 15
(reduce + '(1 2 3) 10)                                   ; => 16
(fold   + 0 '(1 2 3 4 5))                                ; => 15
(fold   (lambda (acc x) (cons x acc)) '() '(1 2 3))      ; => [3, 2, 1]


; ---------------------------------------------------------------------------
; 4. CLOSURES AND HIGHER-ORDER CALLS  ((f x) y) pattern
; ---------------------------------------------------------------------------

(define (make-adder n) (lambda (x) (+ x n)))

((make-adder 5) 10)                   ; => 15
(map (make-adder 100) '(1 2 3))       ; => [101, 102, 103]

(define (compose f g) (lambda (x) (f (g x))))
((compose square (make-adder 1)) 4)   ; => 25   — (4+1)^2


; ---------------------------------------------------------------------------
; 5. MEMOIZATION
; ---------------------------------------------------------------------------

; (memoize f) — wrap any function with a result cache
(define (slow-fib n)
  (if (<= n 1) n
      (+ (slow-fib (- n 1)) (slow-fib (- n 2)))))

(define fast-fib (memoize slow-fib))

(fast-fib 10)    ; => 55   (cached on first call)
(fast-fib 10)    ; => 55   (from cache — instant)
(fast-fib 20)    ; => 6765

; (memoize! 'name) — in-place: self-recursive calls also hit the cache
(define (rec-fib n)
  (if (<= n 1) n
      (+ (rec-fib (- n 1)) (rec-fib (- n 2)))))

(memoize! 'rec-fib)
(rec-fib 30)     ; => 832040   (fast — internal calls are cached too)

(memoized? fast-fib)    ; => true
(memoized? square)      ; => false  (plain function)

; memo-clear! resets the cache
(memo-clear! fast-fib)
(fast-fib 10)    ; => 55   (recomputed from scratch, cached again)


; ---------------------------------------------------------------------------
; 6. MODULE SYSTEM — import, dot-access, open
; ---------------------------------------------------------------------------

(import "examples.ol" e)

(module? e)                  ; => true
(module-name e)              ; => "examples.ol"
(module-origin e)            ; => "file"

e.square                     ; => <Lambda (x)>
(e.square 9)                 ; => 81
(e.cube 3)                   ; => 27
(e.circle-area 1)            ; => 3.14159

(open e)
(square 7)                   ; => 49   — now in scope
tau                          ; => 6.28318


; ---------------------------------------------------------------------------
; 7. INLINE MODULE WITH (export ...)
; ---------------------------------------------------------------------------

(module MyMath
  (export double triple)
  (define (double x) (* 2 x))
  (define (triple x) (* 3 x))
  (define _secret 42)
)

(module? MyMath)              ; => true
(module-exports MyMath)       ; => ["double", "triple"]  (_secret excluded)
(MyMath.double 5)             ; => 10
(MyMath.triple 4)             ; => 12


; ---------------------------------------------------------------------------
; 8. NATIVE MODULE ACCESS
; ---------------------------------------------------------------------------

(import "math" math)

(module? math)                ; => true
(module-origin math)          ; => "native"
(getattr math pi)             ; => 3.141592653589793
((getattr math floor) 3.7)    ; => 3
((getattr math sqrt) 144)     ; => 12.0


; ---------------------------------------------------------------------------
; 9. WITH-MODULE — scoped open (no env pollution)
; ---------------------------------------------------------------------------

; Names from the module are available inside body only
(with-module MyMath
  (double 6))                 ; => 12

; double is NOT in scope here (still the one from (open e) above)
; This verifies with-module doesn't leak into the outer env


; ---------------------------------------------------------------------------
; 10. READER MACROS
; ---------------------------------------------------------------------------

; inc must be defined before the reader macro fires
(define (inc x) (+ x 1))

(register-reader-macro! '~
  (lambda (stream) (list 'inc (read stream))))

~ 5          ; => 6
~ ~ 5        ; => 7

(register-reader-macro! '#
  (lambda (stream) (list 'length (read stream))))

# '(a b c d e)   ; => 5


; ---------------------------------------------------------------------------
; 11. fold FOR TREE TRAVERSAL
; ---------------------------------------------------------------------------

(define (Leaf)          (list 'Leaf))
(define (Node val kids) (list 'Node val kids))
(define (leaf? t)       (= (first t) 'Leaf))
(define (tree-val t)    (second t))
(define (tree-kids t)   (third t))

(define (tree-fold f acc t)
  (if (leaf? t) acc
      (fold (lambda (a kid) (tree-fold f a kid))
            (f acc (tree-val t))
            (tree-kids t))))

(define (tree-depth t)
  (if (leaf? t) 0
      (+ 1 (reduce max (map tree-depth (tree-kids t)) 0))))

(define sample-tree
  (Node 1 (list (Node 2 (list (Node 4 '()) (Node 5 '())))
                (Node 3 (list (Node 6 '()))))))

(tree-fold + 0 sample-tree)    ; => 21
(tree-fold * 1 sample-tree)    ; => 720
(tree-depth sample-tree)       ; => 3


; ---------------------------------------------------------------------------
; 12. STATE MONAD  (((f x) y) higher-order call pattern)
; ---------------------------------------------------------------------------

(define (state-return x)   (lambda (s) (list x s)))
(define (state-get)        (lambda (s) (list s s)))
(define (state-put new-s)  (lambda (s) (list None new-s)))

(define (state-bind m f)
  (lambda (s)
    (let ((result (m s)))
      ((f (first result)) (second result)))))

(define (run-state m initial) (m initial))

(define count-and-increment
  (state-bind (state-get)
    (lambda (n)
      (state-bind (state-put (+ n 1))
        (lambda (_) (state-return n))))))

(run-state count-and-increment 0)   ; => [0, 1]
(run-state count-and-increment 5)   ; => [5, 6]

(define three-counts
  (state-bind count-and-increment
    (lambda (a)
      (state-bind count-and-increment
        (lambda (b)
          (state-bind count-and-increment
            (lambda (c)
              (state-return (list a b c)))))))))

(run-state three-counts 0)   ; => [[0, 1, 2], 3]


; ---------------------------------------------------------------------------
; 13. IMPORT + OPEN + LOAD  (reader macro isolation)
; ---------------------------------------------------------------------------

(import "examples_v2.ol" ev2)

(module? ev2)                ; => true
(module-name ev2)            ; => "examples_v2.ol"

; Explicit export list — should be ~70 names, not 133
(length (module-exports ev2))   ; => ~70  (trimmed by (export ...) in file)

ev2.square                   ; => <Lambda (x)>
(ev2.square 5)               ; => 25
ev2.tau                      ; => 6.28318
ev2.pi                       ; => 3.14159


; ---------------------------------------------------------------------------
; 14. 3-LEVEL DOT ACCESS AND MODULE-QUALIFIED CALLS
; ---------------------------------------------------------------------------

; This verify.ol was itself imported as v, so from outside:
;   v.ev2.square       — 3-level dot chain
;   v.ev2.tau          — 3-level value access
;   (v.square 7)       — module-qualified call
;   (v.run-state v.count-and-increment 0)  — all from module

; Verify the chain works from inside the file too:
(module Inner
  (export get-pi)
  (define (get-pi) 3.14159)
)

(module Outer
  (export inner-pi)
  (define (inner-pi) (Inner.get-pi))
)

; 2-level inline dot access
(Outer.inner-pi)             ; => 3.14159
