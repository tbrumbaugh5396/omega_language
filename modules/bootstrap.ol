; =============================================================================
; modules/bootstrap.ol — Omega Lisp bootstrap & metaprogramming reference
; Run: (load "bootstrap.ol")
;
; Documents how the interpreter's core abstractions are built:
;   macros, quasiquote, ADTs, lazy streams, effects, capabilities
; Each section is self-contained and annotated with expected results.
; =============================================================================


; ---------------------------------------------------------------------------
; 1. DEFMACRO BOOTSTRAP
;    register-macro! is the primitive; defmacro is a macro that registers macros.
; ---------------------------------------------------------------------------

; Bootstrap: register-macro! takes (name params body).
; defmacro is itself defined with register-macro! — a macro that registers macros.
(register-macro! defmacro
  (name params body)
  (list 'register-macro! (list 'quote name) params body))

; Now defmacro is live — use it to define more macros
(defmacro inc (n) `(+ ,n 1))

(inc 3)     ; => 4
(inc 10)    ; => 11


; ---------------------------------------------------------------------------
; 2. ALIASES  (name standardisation)
;    The bootstrap originally used start/prepend/equals; Omega uses first/cons/equal?
; ---------------------------------------------------------------------------

; alias: (alias new-name existing)
(register-macro! alias (new-name existing)
  (list 'define new-name existing))

(alias car   first)
(alias cdr   rest)
(alias cons* cons)

(car  '(1 2 3))    ; => 1
(cdr  '(1 2 3))    ; => (2 3)


; ---------------------------------------------------------------------------
; 3. READER MACROS
;    Omega already has ' ` , ,@ built in.  These show how they could be defined.
; ---------------------------------------------------------------------------

; ' (quote shorthand)
; Already registered by the interpreter — shown here for documentation.
;
; (register-reader-macro! "'
;   (lambda (stream) (list 'quote (read stream))))

'(+ 1 2)           ; => (+ 1 2)  — unevaluated list

; ` (quasiquote), , (unquote), ,@ (unquote-splicing)
; All built into the interpreter.  Example:

(define a 10)
(define b '(20 30))

`(a is ,a and b is ,@b)    ; => (a is 10 and b is 20 30)
`(sum ,(+ a 5))            ; => (sum 15)


; ---------------------------------------------------------------------------
; 4. QUASIQUOTE EXPANDER
;    Demonstrates how a quasiquote expander would be written as a Lisp function.
;    Level-aware so nested quasiquotes work correctly.
; ---------------------------------------------------------------------------

(define (qq-expand x level)
  (cond
    ((atom? x)
     (list 'quote x))
    ((equal? (first x) 'quasiquote)
     (list 'list ''quasiquote (qq-expand (second x) (+ level 1))))
    ((equal? (first x) 'unquote)
     (if (= level 0)
         (second x)
         (list 'list ''unquote (qq-expand (second x) (- level 1)))))
    (else
     (list 'cons
           (qq-expand (first x) level)
           (qq-expand (rest  x) level)))))

; Verify the expander produces correct structure
(qq-expand 'x 0)                    ; => (quote x)
(qq-expand '(unquote y) 0)          ; => y        (level 0: splice)
(qq-expand '(unquote y) 1)          ; => (list (quote unquote) (quote y))  (level 1: keep)


; ---------------------------------------------------------------------------
; 5. ADT SYSTEM  (define-type)
;    Constructors produce tagged lists: (Tag arg1 arg2 ...)
;    is-constructor? checks membership in the global *adt-tags* registry.
; ---------------------------------------------------------------------------

(define *adt-tags* '())

; define-type: emit constructor functions + update *adt-tags* at runtime.
; The set! updates the registry when the expanded code runs, not at expand time.
(register-macro! define-type (name constructors)
  (let ((ctor-defs (map (lambda (ctor)
                          (if (atom? ctor)
                              (list 'define ctor
                                    (list 'lambda '()
                                          (list 'list (list 'quote ctor))))
                              (list 'define (first ctor)
                                    (list 'lambda (rest ctor)
                                          (cons 'list
                                                (cons (list 'quote (first ctor))
                                                      (rest ctor)))))))
                        constructors))
        (tag-list  (map (lambda (c) (list 'quote (if (atom? c) c (first c))))
                        constructors)))
    (cons 'begin
          (cons (list 'set! '*adt-tags*
                      (list 'append (cons 'list tag-list) '*adt-tags*))
                ctor-defs))))

(define (is-constructor? sym)
  (if (null? *adt-tags*) false
      (if (equal? (first *adt-tags*) sym) true
          (is-constructor-in? sym (rest *adt-tags*)))))

(define (is-constructor-in? sym tags)
  (if (null? tags) false
      (if (equal? (first tags) sym) true
          (is-constructor-in? sym (rest tags)))))

; Define Option — using 'Nothing' to avoid shadowing the built-in None sentinel.
; (null? None) must remain true so BST, tree, and other code using None as
; an empty-node marker continues to work after bootstrap loads.
(define-type Option ((Some x) (Nothing)))

(Some 42)              ; => (Some 42)
(Nothing)              ; => (Nothing)
(first (Some 42))      ; => Some   (the tag)
(second (Some 42))     ; => 42     (the value)
(is-constructor? 'Some)    ; => true
(is-constructor? 'Nothing) ; => true
(is-constructor? 'foo)     ; => false

; None remains the built-in empty/null sentinel — null? still works
(null? None)           ; => true

; Define Result
(define-type Result ((Ok value) (Err message)))

(Ok 100)               ; => (Ok 100)
(Err "oops")           ; => (Err oops)
(equal? (first (Err "x")) 'Err)   ; => true


; ---------------------------------------------------------------------------
; 6. AST LOWERING
;    lower-node converts a Lisp expression into a structured AST representation
;    (uam-node kind ...) distinguishing constants, ADT applications, and calls.
; ---------------------------------------------------------------------------

(define (lower-node expr)
  (cond
    ((atom? expr)
     (list 'uam-node ':const expr))
    ((is-constructor? (first expr))
     (list 'uam-node ':adt
           (list 'quote (first expr))
           (map lower-node (rest expr))))
    (else
     (list 'uam-node ':apply
           (lower-node (first expr))
           (map lower-node (rest expr))))))

(lower-node 42)                ; => (uam-node :const 42)
(lower-node '(Some 42))        ; => (uam-node :adt (quote Some) ((uam-node :const 42)))
(lower-node '(f x y))          ; => (uam-node :apply (uam-node :const f) (...))
(lower-node (Some 42))         ; => (uam-node :adt (quote Some) ((uam-node :const 42)))
(lower-node (Err "bad"))       ; => (uam-node :adt (quote Err) ((uam-node :const bad)))


; ---------------------------------------------------------------------------
; 7. LAZY STREAMS  (delay / force / SCons)
;    Infinite sequences via thunks.  SCons stores a head and a delayed tail.
; ---------------------------------------------------------------------------

(define-type Stream ((SCons head tail) (SEmpty)))

(defmacro delay (expr)
  (list 'lambda '() expr))

(define (force thunk) (thunk))

; The infinite stream of 1s
(define (ones)
  (SCons 1 (delay (ones))))

; Take first n elements from a stream
(define (stream-take n stream-fn)
  (if (= n 0) '()
      (let ((s (stream-fn)))
        (cons (second s)                           ; head
              (stream-take (- n 1)
                           (lambda () (force (third s))))))))  ; forced tail

(stream-take 5 ones)    ; => (1 1 1 1 1)

; Natural numbers: 1, 2, 3, ...
(define (nats-from n)
  (SCons n (delay (nats-from (+ n 1)))))

(stream-take 5 (lambda () (nats-from 1)))    ; => (1 2 3 4 5)
(stream-take 5 (lambda () (nats-from 10)))   ; => (10 11 12 13 14)

; Fibonacci stream
(define (fibs-from a b)
  (SCons a (delay (fibs-from b (+ a b)))))

(stream-take 8 (lambda () (fibs-from 0 1)))  ; => (0 1 1 2 3 5 8 13)

; stream-nth: get element n (0-indexed)
(define (stream-nth n stream-fn)
  (if (= n 0)
      (second (stream-fn))
      (stream-nth (- n 1) (lambda () (force (third (stream-fn)))))))

(stream-nth 0 ones)                              ; => 1
(stream-nth 4 (lambda () (nats-from 1)))         ; => 5
(stream-nth 7 (lambda () (fibs-from 0 1)))       ; => 13

; Iterative nth — helper factored out so stream-nth-iter body is one expression
(define (stream-nth-go i fn)
  (if (= i 0)
      (second (fn))
      (stream-nth-go (- i 1) (lambda () (force (third (fn)))))))

(define (stream-nth-iter n stream-fn)
  (stream-nth-go n stream-fn))

(stream-nth-iter 4 (lambda () (nats-from 0)))    ; => 4
(stream-nth-iter 9 (lambda () (fibs-from 0 1)))  ; => 34


; ---------------------------------------------------------------------------
; 8. SAFE SWAP WITH GENSYM
;    gensym generates a unique symbol, preventing capture in hygienic macros.
; ---------------------------------------------------------------------------

(defmacro safe-swap (a b)
  (let ((tmp (gensym)))
    (list 'begin
          (list 'define tmp a)
          (list 'set! a b)
          (list 'set! b tmp))))

(define x 10)
(define y 20)
(safe-swap x y)
x    ; => 20
y    ; => 10

(safe-swap x y)
x    ; => 10    (swapped back)
y    ; => 20


; ---------------------------------------------------------------------------
; 9. WHILE LOOP
;    Imperative iteration via the while special form.
; ---------------------------------------------------------------------------

(define (sum-to n)
  (define total 0)
  (define i 1)
  (while (<= i n)
    (begin
      (set! total (+ total i))
      (set! i (+ i 1))))
  total)

(sum-to 10)    ; => 55
(sum-to 100)   ; => 5050

(define (count-up limit)
  (define result '())
  (define i 0)
  (while (< i limit)
    (begin
      (set! result (append result (list i)))
      (set! i (+ i 1))))
  result)

(count-up 5)   ; => (0 1 2 3 4)


; ---------------------------------------------------------------------------
; 10. CAPABILITIES AND EFFECTS
;     Capabilities gate access to effects at the call site.
;     Calling an effect without the capability raises an error.
; ---------------------------------------------------------------------------

; Define a capability token
(define FS-CAP (new-capability "filesystem"))

; Define an effect that requires the filesystem capability
(define write-log
  (new-effect "filesystem"
    (lambda (path data)
      (string-append "wrote " (number->string (string-length data))
                     " bytes to " path))))

; Without the capability, calling the effect raises:
;   ! Effect Violation: Missing 'filesystem' capability
; (write-log "log.txt" "data")   ; would error

; Capabilities are values — they can be passed and stored
(define (safe-write cap path data)
  (with-capability cap
    (write-log path data)))

; Grant the capability for a lexical scope — try these in the REPL:
; (with-capability FS-CAP (write-log "log.txt" "hello"))  ; => "wrote 5 bytes to log.txt"
; (safe-write FS-CAP "safe.txt" "secure")                 ; => "wrote 6 bytes to safe.txt"


; ---------------------------------------------------------------------------
; 11. MACRO EXPANDER REGISTRY
;     Tracks which names are macros for tooling (pretty-printers, linters).
; ---------------------------------------------------------------------------

(define *macros* '(defmacro define-type delay safe-swap alias inc))

(define (is-macro? sym)
  (if (null? *macros*) false
      (if (equal? (first *macros*) sym) true
          (is-macro-in? sym (rest *macros*)))))

(define (is-macro-in? sym ms)
  (if (null? ms) false
      (if (equal? (first ms) sym) true
          (is-macro-in? sym (rest ms)))))

(is-macro? 'define-type)    ; => true
(is-macro? 'delay)          ; => true
(is-macro? 'lambda)         ; => false
(is-macro? 'inc)            ; => true


; ---------------------------------------------------------------------------
; 12. SAVE IMAGE
;     Persists the current environment to a named snapshot for fast reloads.
; ---------------------------------------------------------------------------

; (save-image "bootstrap-prelude" (find-root))
;   — saves the full environment to "bootstrap-prelude.img"
;   — subsequent sessions can restore with: (load-image "bootstrap-prelude")
