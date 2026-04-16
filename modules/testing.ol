; =============================================================================
; testing.ol — Omega Lisp module system, sealed exports, dot access
; Run: (load "testing.ol")
; Covers: module, open, with-module, dot notation, export sealing, state monad
; =============================================================================


; ---------------------------------------------------------------------------
; 1. BASIC RECURSION + TAIL CALL
; ---------------------------------------------------------------------------

(define (count-down n)
  (if (= n 0) 'lift-off
      (count-down (- n 1))))

(count-down 10)      ; => lift-off
(count-down 1000)    ; => lift-off


; ---------------------------------------------------------------------------
; 2. INLINE MODULE  —  define, export, dot-access
; ---------------------------------------------------------------------------

(module LinearAlgebra
  (export dot-product cross-product magnitude scale)
  (define (dot-product a b)
    (letrec ((go (lambda (xs ys acc)
      (if (null? xs) acc
          (go (rest xs) (rest ys)
              (+ acc (* (first xs) (first ys))))))))
    (go a b 0)))
  (define (cross-product a b)
    ; 3D cross product: (a1,a2,a3) × (b1,b2,b3)
    (list (- (* (second a) (third b)) (* (third a) (second b)))
          (- (* (third a) (first b))  (* (first a) (third b)))
          (- (* (first a) (second b)) (* (second a) (first b)))))
  (define (magnitude v)
    (sqrt (fold + 0 (map (lambda (x) (* x x)) v))))
  (define (scale v k)
    (map (lambda (x) (* x k)) v))
)

(define v1 '(1 2 3))
(define v2 '(4 5 6))

(LinearAlgebra.dot-product v1 v2)      ; => 32
(LinearAlgebra.cross-product v1 v2)    ; => [-3, 6, -3]
(LinearAlgebra.magnitude '(3 4))       ; => 5.0
(LinearAlgebra.scale v1 2)             ; => [2, 4, 6]


; ---------------------------------------------------------------------------
; 3. MODULE WITH CONSTANTS  —  (open ...)  brings names into scope
; ---------------------------------------------------------------------------

(module Constants
  (export pi tau e)
  (define pi  3.141592653589793)
  (define tau (* 2 pi))
  (define e   2.718281828459045)
)

; (Constants.pi)    ; ! TypeError: pi is a value, not a function
Constants.pi      ; => 3.141592653589793
Constants.tau     ; => 6.283185307179586
Constants.e       ; => 2.718281828459045

(open Constants)
pi     ; => 3.141592653589793
tau    ; => 6.283185307179586


; ---------------------------------------------------------------------------
; 4. COMBINED MODULE  —  dot-access across two sub-modules
; ---------------------------------------------------------------------------

(module Physics
  (export gravity-force kinetic-energy)
  (define g 9.81)
  (define (gravity-force mass)    (* mass g))
  (define (kinetic-energy mass v) (* 0.5 mass v v))
)

(Physics.gravity-force 10)          ; => 98.1
(Physics.kinetic-energy 2 3)        ; => 9.0
(Physics.kinetic-energy 70 10)      ; => 3500.0


; ---------------------------------------------------------------------------
; 5. WITH-MODULE  —  scoped access without polluting outer env
; ---------------------------------------------------------------------------

(with-module LinearAlgebra
  (dot-product '(1 0 0) '(0 1 0)))  ; => 0   (orthogonal vectors)

(with-module LinearAlgebra
  (magnitude '(1 1 1)))             ; => 1.7320508075688772

(with-module Physics
  (+ (gravity-force 5) (gravity-force 10)))   ; => 147.15


; ---------------------------------------------------------------------------
; 6. EXPORT SEALING  —  private symbols are not accessible
; ---------------------------------------------------------------------------

(module MathImpl
  (export factorial fib)
  (define _helper-mul (lambda (a b) (* a b)))    ; private
  (define (factorial n)
    (if (<= n 1) 1 (_helper-mul n (factorial (- n 1)))))
  (define (fib n)
    (define (go n a b)
      (if (= n 0) a (go (- n 1) b (+ a b))))
    (go n 0 1))
)

(module-exports MathImpl)     ; => ["factorial", "fib"]  (_helper-mul excluded)
(MathImpl.factorial 10)       ; => 3628800
(MathImpl.fib 20)             ; => 6765

; Attempting to access the private symbol via the module fails:
; (MathImpl._helper-mul 3 4)  ; ! Unbound symbol: _helper-mul


; ---------------------------------------------------------------------------
; 7. NESTED DOT ACCESS  —  module-inside-module
; ---------------------------------------------------------------------------

(module Outer
  (export get-inner-pi compute)
  (module Inner
    (export get-pi)
    (define pi 3.14159)
    (define (get-pi) pi)
  )
  (define (get-inner-pi) (Inner.get-pi))
  (define (compute r) (* (Inner.get-pi) r r))
)

(Outer.get-inner-pi)    ; => 3.14159
(Outer.compute 1)       ; => 3.14159
(Outer.compute 5)       ; => 78.53975
(Outer.Inner.get-pi)    ; => 3.14159   (3-level dot access)


; ---------------------------------------------------------------------------
; 8. STATE MONAD  —  threading state without mutation
; ---------------------------------------------------------------------------

(define (state-return x)   (lambda (s) (list x s)))
(define (state-get)        (lambda (s) (list s s)))
(define (state-put new-s)  (lambda (s) (list '() new-s)))
(define (state-modify f)   (lambda (s) (list '() (f s))))
(define (state-bind m f)
  (lambda (s)
    (let ((result (m s)))
      ((f (first result)) (second result)))))
(define (run-state m initial) (m initial))

; Increment counter, return old value
(define (tick)
  (state-bind (state-get)
    (lambda (n)
      (state-bind (state-put (+ n 1))
        (lambda (_) (state-return n))))))

(run-state (tick) 0)    ; => [0, 1]
(run-state (tick) 5)    ; => [5, 6]

; Chain three ticks: collects [0, 1, 2], leaves state at 3
(define three-ticks
  (state-bind (tick)
    (lambda (a)
      (state-bind (tick)
        (lambda (b)
          (state-bind (tick)
            (lambda (c)
              (state-return (list a b c)))))))))

(run-state three-ticks 0)    ; => [[0, 1, 2], 3]
(run-state three-ticks 10)   ; => [[10, 11, 12], 13]

; state-modify: apply a function to the state without reading it
(run-state
  (state-bind (state-modify (lambda (s) (* s 2)))
    (lambda (_) (state-get)))
  5)                          ; => [10, 10]   — state doubled then read
