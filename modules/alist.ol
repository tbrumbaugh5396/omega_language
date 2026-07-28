;; modules/alist.ol - Dictionary and Mapping Module 

(module Alist

  (export
    ; Dict/map utilities (using alist)
    alist-get alist-set alist-has? alist-keys alist-vals alist-map
  )

  ; ── Alist utilities ──────────────────────────────────────────────────
  ; Alist: list of (key . value) pairs

  (define (alist-get key alist default)
    (let ((entry (filter (lambda (p) (equal? (first p) key)) alist)))
      (if (null? entry) default (second (first entry)))))

  (define (alist-set key val alist)
    (cons (list key val)
          (filter (lambda (p) (not (equal? (first p) key))) alist)))

  (define (alist-has? key alist)
    (list-any (lambda (p) (equal? (first p) key)) alist))

  (define (alist-keys alist) (map first  alist))
  (define (alist-vals alist) (map second alist))

  (define (alist-map f alist)
    (map (lambda (p) (list (first p) (f (second p)))) alist))


) ; end module Alist

(open Alist)