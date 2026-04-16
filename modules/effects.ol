; unit = void/no-meaningful-value
(define unit '())

; effects.ol — Algebraic Effects for Omega Lisp
;
; Implements algebraic effects via shift/reset + Python-level effect-handle.
; Requires: types.ol (loaded first)
;
; Usage: (load "effects.ol")

(load "types.ol")

(module Effects

  (export
    make-effect effect? effect-name
    perform handle on with-handler
    State Reader Writer Exception IO
    run-state get-state put-state modify-state
    run-reader ask local-reader
    run-writer tell
    run-exception throw-exc catch-exc
    run-io io-print io-read IO-CAP
    effect-map)

  ; ── registry ──────────────────────────────────────────────────────────
  (define *effects* '())
  (define (make-effect name) (set! *effects* (cons name *effects*)) name)
  (define (effect? x) (and (symbol? x) (in x *effects*)))
  (define (effect-name e) e)

  ; ── handler clause ────────────────────────────────────────────────────
  (define (on eff fn) (list 'handler eff fn))
  (define (h-eff h) (second h))
  (define (h-fn  h) (third  h))

  ; ── signal helpers ────────────────────────────────────────────────────
  (define (signal? s)
    (and (list? s) (not (null? s)) (equal? (first s) 'effect-signal)))
  (define (sig-eff  s) (second s))
  (define (sig-args s) (third  s))
  (define (sig-cont s) (first (rest (rest (rest s)))))

  ; ── perform ───────────────────────────────────────────────────────────
  (define (perform eff . args)
    (shift k (list 'effect-signal eff args k)))

  ; ── handle ────────────────────────────────────────────────────────────
  ; Delegates to effect-handle special form (Python-level).
  (define (handle handlers thunk)
    (effect-handle handlers thunk))

  ; ── with-handler macro ────────────────────────────────────────────────
  (register-macro! with-handler (__clause__ . __body__)
    `(handle (list ,__clause__) (lambda () ,@__body__)))

  ; ── unit value ────────────────────────────────────────────────────────
  ; Use '() as the unit/void return value (null? returns true for it).
  (define unit '())

  ; ── built-in effects ─────────────────────────────────────────────────
  (define State     (make-effect 'State))
  (define Reader    (make-effect 'Reader))
  (define Writer    (make-effect 'Writer))
  (define Exception (make-effect 'Exception))
  (define IO        (make-effect 'IO))

  ; ── last helper ───────────────────────────────────────────────────────
  (define (last lst)
    (if (null? (rest lst)) (first lst) (last (rest lst))))

  ; ── State ─────────────────────────────────────────────────────────────
  (define (get-state)      (perform State 'get))
  (define (put-state s)    (perform State 'put s))
  (define (modify-state f) (put-state (f (get-state))))

  (define (run-state initial thunk)
    (let ((cell (list initial)))
      (let ((val
             (handle
               (list (on State
                       (lambda args
                         (let ((op (first args))
                               (k  (last  args)))
                           (cond
                             ((equal? op 'get) (k (first cell)))
                             ((equal? op 'put)
                              (set! cell (list (second args)))
                              (k '()))
                             (else (error! "Unknown State op")))))))
               thunk)))
        (Pair val (first cell)))))

  ; ── Reader ────────────────────────────────────────────────────────────
  (define (ask) (perform Reader 'ask))

  (define (run-reader env-val thunk)
    (handle
      (list (on Reader
               (lambda (op k)
                 (if (equal? op 'ask) (k env-val)
                     (error! "Unknown Reader op")))))
      thunk))

  (define (local-reader f thunk) (run-reader (f (ask)) thunk))

  ; ── Writer ────────────────────────────────────────────────────────────
  (define (tell x) (perform Writer 'tell x))

  (define (run-writer thunk)
    (let ((log (list '())))
      (let ((val
             (handle
               (list (on Writer
                       (lambda (op x k)
                         (if (equal? op 'tell)
                             (begin
                               (set! log (list (append (first log) (list x))))
                               (k '()))
                             (error! "Unknown Writer op")))))
               thunk)))
        (Pair val (first log)))))

  ; ── Exception ─────────────────────────────────────────────────────────
  (define (throw-exc msg) (perform Exception 'throw msg))

  (define (run-exception thunk)
    (handle
      (list (on Exception
               (lambda (op msg k)
                 (if (equal? op 'throw) (Err msg)
                     (error! "Unknown Exception op")))))
      (lambda () (Ok (thunk)))))

  (define (catch-exc thunk handler-fn)
    (handle
      (list (on Exception
               (lambda (op msg k)
                 (if (equal? op 'throw) (handler-fn msg)
                     (error! "Unknown Exception op")))))
      thunk))

  ; ── IO ────────────────────────────────────────────────────────────────
  (define IO-CAP (new-capability "io"))
  (define (io-print msg)   (perform IO 'print msg))
  (define (io-read prompt) (perform IO 'read  prompt))

  (define (run-io thunk)
    (handle
      (list (on IO
               (lambda (op arg k)
                 (cond
                   ((equal? op 'print) (print arg) (k '()))
                   ((equal? op 'read)
                    (k (py-eval (string-append "input('" arg "')"))))
                   (else (error! "Unknown IO op"))))))
      thunk))

  ; ── utility ───────────────────────────────────────────────────────────
  (define (effect-map f thunk)
    (handle '() (lambda () (f (thunk)))))

) ; end module Effects

(open Effects)
