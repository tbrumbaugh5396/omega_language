;; modules/predicate.ol - combine predicates together

(module Predicate

  (export
    ; Predicate combinators
    negate both? either?
  )

  ; ── Predicate combinators ────────────────────────────────────────────

  ;; (define not-even (pred.negate math.even?))
  ;; (not-even 3)
  (define (negate pred) (lambda (x) (not (pred x))))
  (define (both? p q)   (lambda (x) (and (p x) (q x))))
  (define (either? p q) (lambda (x) (or  (p x) (q x))))

) ; end module Predicate

(open Predicate)