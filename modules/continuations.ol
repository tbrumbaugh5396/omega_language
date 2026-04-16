; continuations.ol — Delimited Continuations for Omega Lisp
;
; New special forms:
;   (reset expr)              — establish a delimiter; evaluate expr
;   (shift k body)            — capture continuation into k; run body; abort to reset
;   (continuation? x)         — true if x is a continuation
;   (multi-shot! k)           — make k reusable (default is one-shot)
;
; Load this file to get all utility functions built on top.

; ============================================================
; PART 1: Core semantics demonstrations
; ============================================================

; reset without shift — pure identity
; (reset 42)           => 42
; (reset (+ 1 2))      => 3

; shift with no k call — abort to reset, return body value
; (reset (+ 1 (shift k 10)))   => 10   (+ 1 ... is skipped)
; (reset (* 5 (shift k 99)))   => 99

; shift calling k — resume the captured continuation
; (reset (+ 1 (shift k (k 5))))    => 6    k = "add 1 to hole"
; (reset (* 3 (shift k (k 4))))    => 12   k = "multiply 3 by hole"
; (reset (+ 2 (* 3 (shift k (k 4))))) => 14

; ============================================================
; PART 2: Early exit / non-local return
; ============================================================

; find-first: return the first matching element without scanning the rest
(define (find-first pred lst)
  (reset
    (begin
      (for-each
        (lambda (x)
          (if (pred x)
              (shift k x)    ; abort immediately with x; k is never called
              None))
        lst)
      None)))   ; default if nothing matches

; find-index: return index of first match
(define (find-index pred lst)
  (reset
    (letrec ((loop (lambda (i remaining)
      (if (null? remaining)
          None
          (if (pred (first remaining))
              (shift k i)
              (loop (+ i 1) (rest remaining)))))))
      (loop 0 lst))))

; any?: true if any element satisfies pred (short-circuits)
(define (any? pred lst)
  (reset
    (begin
      (for-each
        (lambda (x)
          (if (pred x) (shift k true) None))
        lst)
      false)))

; Example:
; (find-first number? (list "a" "b" 3 "c"))   => 3
; (find-index even?   (list 1 3 4 5 6))        => 2
; (any? negative?     (list 1 2 -1 4))         => true

; ============================================================
; PART 3: Generator / lazy sequence
; ============================================================

; make-generator: turns any loop body into a lazy sequence.
; The body uses (yield x) to produce values one at a time.
; Caller uses (next) to advance.

(define (make-generator thunk)
  (define resume None)
  (define done false)
  (define (next)
    (if done 'done
        (if (null? resume)
            (reset
              (begin
                (thunk)
                (set! done true)
                'done))
            (resume None))))
  next)

; yield: inside a generator body, produce one value and suspend
(define (yield x)
  (shift k
    (begin
      (set! resume (multi-shot! k))
      x)))

; make-range: integer range generator
(define (make-range n)
  (define resume None)
  (define done false)
  (define (next)
    (if done 'done
        (if (null? resume)
            (reset
              (letrec ((loop (lambda (i)
                (if (< i n)
                    (begin
                      (shift k
                        (begin (set! resume (multi-shot! k)) i))
                      (loop (+ i 1)))
                    (begin (set! done true) 'done)))))
                (loop 0)))
            (resume None))))
  next)

; collect: drain a generator into a list
(define (collect gen)
  (letrec ((loop (lambda (acc)
    (let ((v (gen)))
      (if (equal? v 'done)
          (reverse acc)
          (loop (cons v acc)))))))
    (loop '())))

; take: first n values from a generator
(define (take n gen)
  (letrec ((loop (lambda (i acc)
    (if (= i 0) (reverse acc)
        (let ((v (gen)))
          (if (equal? v 'done) (reverse acc)
              (loop (- i 1) (cons v acc))))))))
    (loop n '())))

; Examples:
; (define g (make-range 5))
; (g) => 0   (g) => 1   (g) => 2   ...
; (collect (make-range 5))  => (0 1 2 3 4)
; (take 3 (make-range 100)) => (0 1 2)

; ============================================================
; PART 4: Coroutines
; ============================================================

; Two coroutines that take turns running.
; Each calls (yield-to other) to hand control over.

(define (make-coroutine body)
  (define resume None)
  (define started false)
  (define (step msg)
    (if started
        (if (null? resume)
            'finished
            (resume msg))
        (begin
          (set! started true)
          (reset (body step)))))
  step)

; Example — ping-pong:
; (define pong None)
; (define ping
;   (make-coroutine
;     (lambda (self)
;       (print "ping")
;       (shift k (begin (set! resume (multi-shot! k)) (pong "hi")))
;       (print "ping again")
;       (shift k (begin (set! resume (multi-shot! k)) (pong "bye"))))))
; (set! pong
;   (make-coroutine
;     (lambda (self)
;       (print "pong")
;       (shift k (begin (set! resume (multi-shot! k)) (ping "hi")))
;       (print "pong again"))))
; (ping None)

; ============================================================
; PART 5: CPS on demand
; ============================================================

; With shift/reset you can write CPS-style code when you want it,
; without transforming your whole program.

; CPS addition: (cps-add a b k) calls k with (+ a b)
(define (cps-add a b k) (k (+ a b)))

; Use it directly:
; (reset (cps-add 3 4 (lambda (r) (shift _ r)))) => 7

; Or chain:
; (reset
;   (cps-add 1 2
;     (lambda (r1)
;       (cps-add r1 10
;         (lambda (r2)
;           (shift _ r2))))) ) => 13

; ============================================================
; PART 6: Backtracking search (multi-shot)
; ============================================================

; A simple backtracking framework using multi-shot continuations.
; (amb x y z) tries each value; (fail) backtracks.

(define fail-stack '())

(define (amb . choices)
  (shift k
    (begin
      (for-each
        (lambda (choice)
          (set! fail-stack
            (cons (lambda () (k choice)) fail-stack)))
        (reverse choices))
      (if (null? fail-stack)
          (error! "No solution found")
          (let ((try (first fail-stack)))
            (set! fail-stack (rest fail-stack))
            (try))))))

(define (fail)
  (if (null? fail-stack)
      (error! "No more choices")
      (let ((try (first fail-stack)))
        (set! fail-stack (rest fail-stack))
        (try))))

; Example: find two numbers that sum to 10
; (reset
;   (let ((a (amb 1 2 3 4 5 6 7 8 9))
;         (b (amb 1 2 3 4 5 6 7 8 9)))
;     (if (= (+ a b) 10)
;         (list a b)
;         (fail))))

; ============================================================
; PART 7: async/await pattern
; ============================================================

; Model async computations as continuations.
; (async-run thunk) evaluates thunk, returning a "promise".
; (await promise) inside a reset block gets the value.

(define pending-tasks '())

(define (async-run thunk)
  ; Returns a promise — a function that delivers the value when ready
  (define value None)
  (define callbacks '())
  (define resolved false)
  (define (resolve! v)
    (set! value v)
    (set! resolved true)
    (for-each (lambda (cb) (cb v)) callbacks))
  (define (then cb)
    (if resolved
        (cb value)
        (set! callbacks (cons cb callbacks))))
  ; Schedule the thunk (run immediately in this simple model)
  (resolve! (thunk))
  then)

(define (await promise)
  (shift k
    (promise (multi-shot! k))))

; Example:
; (reset
;   (let ((x (await (async-run (lambda () (+ 1 2)))))
;         (y (await (async-run (lambda () (* 3 4))))))
;     (+ x y)))     => 15

(print "continuations.ol loaded.")
(print "New forms: reset  shift  continuation?  multi-shot!")
(print "")
(print "Quick demo:")
(print "  (reset (+ 1 (shift k 10)))       => 10  (pure abort)")
(print "  (reset (+ 1 (shift k (k 5))))    => 6   (invoke k)")
(print "  (collect (make-range 5))          => (0 1 2 3 4)")
(print "  (find-first even? (list 1 3 4 6)) => 4")
