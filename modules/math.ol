;; =============================================================================
;; modules/math.ol — Python math module wrapper for Omega Lisp
;; Run: (import "math.ol" math)  or  (import "modules/math.ol" math)
;;
;; Wraps Python's math stdlib, exposing constants and functions as
;; first-class Omega values accessible via dot notation.
;; =============================================================================

(module math
  (export
    ; Constants
    pi e tau inf nan
    ; Rounding
    floor ceil trunc
    ; Powers / roots
    sqrt pow exp log log2 log10
    ; Trig
    sin cos tan asin acos atan atan2
    ; Hyperbolic
    sinh cosh tanh
    ; Misc
    abs fabs factorial gcd lcm
    isfinite isinf isnan
    degrees radians
    hypot
    ; old
    square cube min max abs clamp even? odd? fib factorial lerp sign
    ;
    LinearAlgebra Vector
  )

  ; Pull in the Python math module once
  (import "math" _m)

  ; Constants
  (define pi  (getattr _m pi))
  (define e   (getattr _m e))
  (define tau (getattr _m tau))
  (define inf (getattr _m inf))
  (define nan (getattr _m nan))

  ; Rounding
  (define floor    (getattr _m floor))
  (define ceil     (getattr _m ceil))
  (define trunc    (getattr _m trunc))

  ; Powers / roots
  (define sqrt     (getattr _m sqrt))
  (define pow      (getattr _m pow))
  (define exp      (getattr _m exp))
  (define log      (getattr _m log))
  (define log2     (getattr _m log2))
  (define log10    (getattr _m log10))

  ; Trig (radians)
  (define sin      (getattr _m sin))
  (define cos      (getattr _m cos))
  (define tan      (getattr _m tan))
  (define asin     (getattr _m asin))
  (define acos     (getattr _m acos))
  (define atan     (getattr _m atan))
  (define atan2    (getattr _m atan2))

  ; Hyperbolic
  (define sinh     (getattr _m sinh))
  (define cosh     (getattr _m cosh))
  (define tanh     (getattr _m tanh))

  ; Misc
  (define abs      (getattr _m fabs))   ; float abs
  (define fabs     (getattr _m fabs))
  (define factorial (getattr _m factorial))
  (define gcd      (getattr _m gcd))
  (define lcm      (getattr _m lcm))
  (define isfinite (getattr _m isfinite))
  (define isinf    (getattr _m isinf))
  (define isnan    (getattr _m isnan))
  (define degrees  (getattr _m degrees))
  (define radians  (getattr _m radians))
  (define hypot    (getattr _m hypot))

  ; ── Math utilities ───────────────────────────────────────────────────

  (define (min a b) (if (< a b) a b))
  (define (max a b) (if (> a b) a b))
  (define (abs x) (if (< x 0) (- 0 x) x))

  (define (clamp x lo hi)
    (max lo (min x hi)))

  (define (lerp a b t) (+ a (* t (- b a))))

  (define (sign x)
    (cond ((> x 0)  1)
          ((< x 0) -1)
          (else     0)))

  (define (even? n) (= (mod n 2) 0))
  (define (odd? n) (not (even? n)))

  (define (fib n)
    (define (go n a b)
      (if (= n 0) a (go (- n 1) b (+ a b))))
    (go n 0 1))

  (define (factorial n)
    (define (go n acc)
      (if (= n 0) acc (go (- n 1) (* acc n))))
    (go n 1))

  (module LinearAlgebra
    ;; (LinearAlgebra.dot-product (list 1) (list 2)) => 2
    (define dot-product 
        (lambda (a b)
            (if (null? a)
                0
                (+ (* (first a) (first b)) 
                   (dot-product (rest a) (rest b))))))

    (define matrix-identity-2x2 
        (list (list 1 0) (list 0 1))))

  (module Vector
      (define magnitude 
          (lambda (v)
              (sqrt (LinearAlgebra.dot-product v v))))

      (define normalize 
          (lambda (v)
              (map (lambda (x) (/ x (magnitude v))) v))))

  (module Constants
    (define-const PI 3.1415926535)
    (define-const E  2.7182818284))

  (define fact 
      (lambda (n) 
          (if (= n 0) 1 (* n (fact (- n 1)))))
)
