; =============================================================================
; test2.ol — Omega Lisp iteration, Pi estimation, macro patterns
; Run: (load "test2.ol")
; Covers: letrec loops, let binding, functional iteration, macro-built loops
; =============================================================================


; ---------------------------------------------------------------------------
; 0. HELPERS
; ---------------------------------------------------------------------------

(define (last lst)
  (if (null? (rest lst)) (first lst) (last (rest lst))))


; ---------------------------------------------------------------------------
; 1. FUNCTIONAL ITERATOR  (replacing dotimes + setq)
; ---------------------------------------------------------------------------

; The core loop: iterate i from 0 to count-1, calling body-fn each time
(define (do-iter count body-fn)
  (define (go i)
    (if (>= i count) '()
        (begin (body-fn i) (go (+ i 1)))))
  (go 0))

; Collect results into a list
(define (build-list count fn)
  (define (go i acc)
    (if (>= i count) (reverse acc)
        (go (+ i 1) (cons (fn i) acc))))
  (go 0 '()))

(build-list 5 (lambda (i) (* i i)))   ; => [0, 1, 4, 9, 16]
(build-list 4 (lambda (i) (+ i 10)))  ; => [10, 11, 12, 13]


; ---------------------------------------------------------------------------
; 2. TIMES MACRO  (clean loop syntax)
; ---------------------------------------------------------------------------

; (times n body...) — run body n times, return ()
(register-macro! times (n . body)
  `(do-iter ,n (lambda (_) ,@body)))

; (collect n fn) — build list of n values, index bound to i
(register-macro! collect (n i body)
  `(build-list ,n (lambda (,i) ,body)))

(collect 6 i (* i 2))              ; => [0, 2, 4, 6, 8, 10]
(collect 5 i (** 2 i))           ; => [1, 2, 4, 8, 16]


; ---------------------------------------------------------------------------
; 3. PI ESTIMATION — Leibniz series  (replacing the CL version)
; ---------------------------------------------------------------------------
;
; π/4 = 1 - 1/3 + 1/5 - 1/7 + ...
; sum = (1/1 - 1/3) + (1/5 - 1/7) + ...  (paired terms)
; Each pair contributes 1/inc - 1/(inc+2)

(define (estimate-pi degree)
  (letrec ((loop (lambda (i sum inc)
    (if (>= i degree)
        (* 4 sum)
        (let ((term (+ (/ 1 inc) (/ -1 (+ inc 2)))))
          (loop (+ i 1) (+ sum term) (+ inc 4)))))))
  (loop 0 0 1)))

(estimate-pi 10)      ; => ~3.0418  (rough)
(estimate-pi 100)     ; => ~3.1411  (closer)
(estimate-pi 1000)    ; => ~3.14159 (good)
(estimate-pi 10000)   ; => ~3.14159 (very close to π)

; Check convergence: each call should be closer to π
(define (pi-error n)
  (abs (- (estimate-pi n) 3.141592653589793)))

(< (pi-error 1000) (pi-error 100))        ; => true
(< (pi-error 10000) (pi-error 1000))      ; => true
(< (pi-error 10000) 0.0002)               ; => true


; ---------------------------------------------------------------------------
; 4. ACCUMULATOR PATTERN  (replacing setf/setq mutation)
; ---------------------------------------------------------------------------
;
; Omega style: pass accumulators through recursion or letrec.
; No mutable variables needed.

(define (running-sum lst)
  (letrec ((go (lambda (rem total acc)
    (if (null? rem)
        (reverse acc)
        (let ((new-total (+ total (first rem))))
          (go (rest rem) new-total (cons new-total acc)))))))
  (go lst 0 '())))

(running-sum '(1 2 3 4 5))    ; => [1, 3, 6, 10, 15]
(running-sum '(10 20 30))     ; => [10, 30, 60]

; Equivalent using fold
(define (running-sum-fold lst)
  (second (fold (lambda (state x)
                  (let ((total (+ (first state) x)))
                    (list total (append (second state) (list total)))))
                (list 0 '())
                lst)))

(running-sum-fold '(1 2 3 4 5))   ; => [1, 3, 6, 10, 15]


; ---------------------------------------------------------------------------
; 5. HIGHER-ORDER LOOP PATTERNS
; ---------------------------------------------------------------------------

; repeat-until: loop until predicate returns true, collecting values
(define (repeat-until pred step init max-iters)
  (letrec ((go (lambda (val i acc)
    (cond
      ((pred val)     (reverse (cons val acc)))
      ((>= i max-iters) (reverse acc))
      (else           (go (step val) (+ i 1) (cons val acc)))))))
  (go init 0 '())))

; Halving sequence until < 0.01
(repeat-until (lambda (x) (< x 0.01))
              (lambda (x) (/ x 2))
              1.0
              20)     ; => [1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125]

; Collatz sequence
(define (collatz n)
  (repeat-until (lambda (x) (= x 1))
                (lambda (x) (if (= (mod x 2) 0) (/ x 2) (+ (* 3 x) 1)))
                n
                1000))

(collatz 6)     ; => [6, 3, 10, 5, 16, 8, 4, 2, 1]
(collatz 27)    ; => long sequence (Collatz conjecture), ends in 1
(last (collatz 27))   ; => 1
