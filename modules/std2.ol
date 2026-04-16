; std.ol — Standard Library for Omega Lisp
;
; Loads the type and effect systems and adds common utilities.
; Designed to be the single import for application code.
;
; Usage:  (load "std.ol")
;         (import "std.ol" std)

(load "types.ol")
(load "effects.ol")

(module Std

  (export
    ; String utilities
    str-join str-split-lines str-trim str-starts-with str-ends-with
    str-pad-left str-pad-right str-repeat str-contains
    ; List utilities
    list-last list-init list-flatten list-zip list-unzip
    list-group-by list-partition list-range
    list-take list-drop list-take-while list-drop-while
    list-any list-all list-find list-find-index
    list-sum list-product list-min list-max list-mean
    list-unique list-count list-intersect list-union list-diff
    ; Math utilities
    square cube clamp lerp sign
    ; Function utilities
    pipe thread-first thread-last memoize-fn
    ; Dict/map utilities (using alist)
    alist-get alist-set alist-has? alist-keys alist-vals alist-map
    ; Predicate combinators
    negate both? either?
    ; Debug
    debug-print trace-val)

  ; ── String utilities ─────────────────────────────────────────────────

  (define (str-join sep lst)
    (if (null? lst) ""
        (if (null? (rest lst)) (first lst)
            (string-append (first lst) sep (str-join sep (rest lst))))))

  (define (str-split-lines s)
    (string-split s "\n"))

  (define (str-trim s)
    (py-eval (string-append "'" s "'.strip()")))

  (define (str-starts-with s prefix)
    (and (>= (string-length s) (string-length prefix))
         (equal? (substring s 0 (string-length prefix)) prefix)))

  (define (str-ends-with s suffix)
    (let ((sl (string-length s))
          (xl (string-length suffix)))
      (and (>= sl xl)
           (equal? (substring s (- sl xl) sl) suffix))))

  (define (str-pad-left s width char)
    (let ((pad (- width (string-length s))))
      (if (<= pad 0) s
          (string-append (str-repeat char pad) s))))

  (define (str-pad-right s width char)
    (let ((pad (- width (string-length s))))
      (if (<= pad 0) s
          (string-append s (str-repeat char pad)))))

  (define (str-repeat ch n)
    (if (<= n 0) ""
        (string-append ch (str-repeat ch (- n 1)))))

  (define (str-contains s sub)
    (string-contains s sub))

  ; ── List utilities ───────────────────────────────────────────────────

  (define (list-last lst)
    (if (null? (rest lst)) (first lst)
        (list-last (rest lst))))

  (define (list-init lst)
    (if (null? (rest lst)) '()
        (cons (first lst) (list-init (rest lst)))))

  (define (list-flatten lst)
    (cond ((null? lst) '())
          ((list? (first lst))
           (append (list-flatten (first lst)) (list-flatten (rest lst))))
          (else (cons (first lst) (list-flatten (rest lst))))))

  (define (list-zip a b)
    (if (or (null? a) (null? b)) '()
        (cons (list (first a) (first b))
              (list-zip (rest a) (rest b)))))

  (define (list-unzip pairs)
    (if (null? pairs)
        (list '() '())
        (let* ((rest-unzipped (list-unzip (rest pairs)))
               (first-pair    (first pairs)))
          (list (cons (first first-pair) (first rest-unzipped))
                (cons (second first-pair) (second rest-unzipped))))))

  (define (list-group-by key-fn lst)
    ; Returns alist of (key . items)
    (fold (lambda (acc item)
            (let* ((k   (key-fn item))
                   (grp (alist-get k acc '())))
              (alist-set k (append grp (list item)) acc)))
          '() lst))

  (define (list-partition pred lst)
    (list (filter pred lst)
          (filter (lambda (x) (not (pred x))) lst)))

  (define (list-range start end)
    (if (>= start end) '()
        (cons start (list-range (+ start 1) end))))

  (define (list-take n lst)
    (if (or (= n 0) (null? lst)) '()
        (cons (first lst) (list-take (- n 1) (rest lst)))))

  (define (list-drop n lst)
    (if (or (= n 0) (null? lst)) lst
        (list-drop (- n 1) (rest lst))))

  (define (list-take-while pred lst)
    (if (or (null? lst) (not (pred (first lst)))) '()
        (cons (first lst) (list-take-while pred (rest lst)))))

  (define (list-drop-while pred lst)
    (if (or (null? lst) (not (pred (first lst)))) lst
        (list-drop-while pred (rest lst))))

  (define (list-any pred lst)
    (and (not (null? lst))
         (or (pred (first lst)) (list-any pred (rest lst)))))

  (define (list-all pred lst)
    (or (null? lst)
        (and (pred (first lst)) (list-all pred (rest lst)))))

  (define (list-find pred lst)
    (cond ((null? lst) None)
          ((pred (first lst)) (Some (first lst)))
          (else (list-find pred (rest lst)))))

  (define (list-find-index pred lst)
    (letrec ((go (lambda (i l)
                   (cond ((null? l) None)
                         ((pred (first l)) (Some i))
                         (else (go (+ i 1) (rest l)))))))
      (go 0 lst)))

  (define (list-sum lst) (fold + 0 lst))
  (define (list-product lst) (fold * 1 lst))

  (define (list-min lst)
    (fold (lambda (acc x) (if (< x acc) x acc)) (first lst) (rest lst)))

  (define (list-max lst)
    (fold (lambda (acc x) (if (> x acc) x acc)) (first lst) (rest lst)))

  (define (list-mean lst)
    (if (null? lst) 0
        (/ (list-sum lst) (length lst))))

  (define (list-unique lst)
    (letrec ((go (lambda (seen remaining)
                   (if (null? remaining) '()
                       (let ((x (first remaining)))
                         (if (in x seen)
                             (go seen (rest remaining))
                             (cons x (go (cons x seen) (rest remaining)))))))))
      (go '() lst)))

  (define (list-count pred lst)
    (fold (lambda (acc x) (if (pred x) (+ acc 1) acc)) 0 lst))

  (define (list-intersect a b)
    (filter (lambda (x) (in x b)) a))

  (define (list-union a b)
    (append a (filter (lambda (x) (not (in x a))) b)))

  (define (list-diff a b)
    (filter (lambda (x) (not (in x b))) a))

  ; ── Math utilities ───────────────────────────────────────────────────

  (define (square x) (* x x))
  (define (cube x)   (* x x x))

  (define (clamp lo hi x)
    (cond ((< x lo) lo)
          ((> x hi) hi)
          (else x)))

  (define (lerp a b t) (+ a (* t (- b a))))

  (define (sign x)
    (cond ((> x 0)  1)
          ((< x 0) -1)
          (else     0)))

  ; ── Function utilities ───────────────────────────────────────────────

  (define (pipe . fns)
    (lambda (x) (fold (lambda (v f) (f v)) x fns)))

  (define (thread-first x . fns)
    ((apply pipe fns) x))

  (define (thread-last x . fns)
    (fold (lambda (acc f) (f acc)) x fns))

  (define (memoize-fn f)
    (define cache '())
    (lambda args
      (let ((cached (alist-get args cache None)))
        (if (not (equal? cached None))
            cached
            (let ((result (apply f args)))
              (set! cache (alist-set args result cache))
              result)))))

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

  ; ── Predicate combinators ────────────────────────────────────────────

  (define (negate pred) (lambda (x) (not (pred x))))
  (define (both? p q)   (lambda (x) (and (p x) (q x))))
  (define (either? p q) (lambda (x) (or  (p x) (q x))))

  ; ── Debug ────────────────────────────────────────────────────────────

  (define (debug-print label val)
    (print (string-append "[DEBUG] " label ": " (py-eval (string-append "repr(" (number->string 0) ")"))))
    val)

  (define (trace-val label val)
    (print (string-append label ": " (number->string val)))
    val)

) ; end module Std

(open Std)
