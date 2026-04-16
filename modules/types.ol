; types.ol — Algebraic Data Types for Omega Lisp
;
; Provides: Option, Result, Either, Pair, Stream, and generic ADT machinery.
; Works with the algebraic effects system in effects.ol.
;
; Usage:  (load "types.ol")

(module Types

  (export
    ; ADT core
    define-type tag-of tag=? adt?
    ; Option  (Some x | None)
    Some None some? none? option-map option-bind option-get option-or
    ; Result  (Ok x | Err e)
    Ok Err ok? err? result-map result-bind result-get result-or result-or-else
    ; Either  (Left x | Right x)
    Left Right left? right? either-map either-bind either-fold
    ; Pair
    Pair pair? pair-first pair-second pair-map
    ; Stream  (Cons head tail-thunk | Empty)
    StreamCons StreamEmpty stream-cons stream-empty? stream-head stream-tail
    stream-take stream-drop stream-map stream-filter stream-fold
    stream-from stream-range stream-repeat stream-iterate
    stream->list list->stream stream-zip stream-append
    ; Utility
    identity const flip compose)

  ; ── ADT infrastructure ───────────────────────────────────────────────
  ; Every ADT value is a list: (tag arg1 arg2 ...)
  ; tag-of returns the constructor name as a symbol.

  (define (tag-of v)
    (if (and (list? v) (not (null? v))) (first v) None))

  (define (tag=? t v)
    (equal? (tag-of v) t))

  (define (adt? v)
    (and (list? v) (not (null? v)) (symbol? (first v))))

  ; ── define-type macro ────────────────────────────────────────────────
  ; (define-type TypeName (Con1) (Con2 field1 field2) ...)
  ; Defines constructor functions and a predicate TypeName?
  ; Con1 → (define (Con1) (list 'Con1))
  ; Con2 → (define (Con2 a b) (list 'Con2 a b))

  (register-macro! define-type (__dt_name__ . __dt_ctors__)
    `(begin
       ,@(map (lambda (__ctor__)
                (if (list? __ctor__)
                    (let* ((cname  (first __ctor__))
                           (fields (rest __ctor__)))
                      `(define (,cname ,@fields) (list ',cname ,@fields)))
                    `(define (,__ctor__) (list ',__ctor__))))
              __dt_ctors__)))

  ; ── Option ───────────────────────────────────────────────────────────
  (define (Some x)    (list 'Some x))
  (define (None)      (list 'None))
  (define (some? v)   (tag=? 'Some v))
  (define (none? v)   (tag=? 'None v))

  (define (option-map f opt)
    (if (some? opt) (Some (f (second opt))) (None)))

  (define (option-bind f opt)
    (if (some? opt) (f (second opt)) (None)))

  (define (option-get opt default)
    (if (some? opt) (second opt) default))

  (define (option-or opt alternative)
    (if (some? opt) opt alternative))

  ; ── Result ───────────────────────────────────────────────────────────
  (define (Ok x)      (list 'Ok x))
  (define (Err e)     (list 'Err e))
  (define (ok? v)     (tag=? 'Ok v))
  (define (err? v)    (tag=? 'Err v))

  (define (result-map f res)
    (if (ok? res) (Ok (f (second res))) res))

  (define (result-bind f res)
    (if (ok? res) (f (second res)) res))

  (define (result-get res default)
    (if (ok? res) (second res) default))

  (define (result-or res fallback)
    (if (ok? res) res fallback))

  (define (result-or-else res f)
    (if (err? res) (f (second res)) res))

  ; ── Either ───────────────────────────────────────────────────────────
  (define (Left x)    (list 'Left x))
  (define (Right x)   (list 'Right x))
  (define (left? v)   (tag=? 'Left v))
  (define (right? v)  (tag=? 'Right v))

  (define (either-map f-left f-right e)
    (cond ((left? e)  (Left  (f-left  (second e))))
          ((right? e) (Right (f-right (second e))))
          (else e)))

  (define (either-bind f e)
    (if (right? e) (f (second e)) e))

  (define (either-fold f-left f-right e)
    (cond ((left? e)  (f-left  (second e)))
          ((right? e) (f-right (second e)))
          (else None)))

  ; ── Pair ─────────────────────────────────────────────────────────────
  (define (Pair a b)  (list 'Pair a b))
  (define (pair? v)   (tag=? 'Pair v))
  (define (pair-first v)  (second v))
  (define (pair-second v) (third v))
  (define (pair-map f p)  (Pair (f (pair-first p)) (f (pair-second p))))

  ; ── Stream ───────────────────────────────────────────────────────────
  ; Lazy stream: StreamCons wraps (head . thunk) where thunk is (lambda () next-stream)
  (define (StreamCons h thunk) (list 'StreamCons h thunk))
  (define (StreamEmpty)        (list 'StreamEmpty))
  (define (stream-cons h thunk) (StreamCons h thunk))
  (define (stream-empty? s)    (tag=? 'StreamEmpty s))
  (define (stream-head s)      (if (stream-empty? s) None (second s)))
  (define (stream-tail s)      (if (stream-empty? s) (StreamEmpty)
                                    ((third s))))   ; force the thunk

  (define (stream-take n s)
    (if (or (= n 0) (stream-empty? s))
        '()
        (cons (stream-head s)
              (stream-take (- n 1) (stream-tail s)))))

  (define (stream-drop n s)
    (if (or (= n 0) (stream-empty? s)) s
        (stream-drop (- n 1) (stream-tail s))))

  (define (stream-map f s)
    (if (stream-empty? s) (StreamEmpty)
        (StreamCons (f (stream-head s))
                    (lambda () (stream-map f (stream-tail s))))))

  (define (stream-filter pred s)
    (cond ((stream-empty? s) (StreamEmpty))
          ((pred (stream-head s))
           (StreamCons (stream-head s)
                       (lambda () (stream-filter pred (stream-tail s)))))
          (else (stream-filter pred (stream-tail s)))))

  (define (stream-fold f acc s)
    (if (stream-empty? s) acc
        (stream-fold f (f acc (stream-head s)) (stream-tail s))))

  ; stream-from: infinite stream of integers starting at n
  (define (stream-from n)
    (StreamCons n (lambda () (stream-from (+ n 1)))))

  ; stream-range: finite range [start, end)
  (define (stream-range start end)
    (if (>= start end) (StreamEmpty)
        (StreamCons start (lambda () (stream-range (+ start 1) end)))))

  ; stream-repeat: infinite stream of same value
  (define (stream-repeat x)
    (StreamCons x (lambda () (stream-repeat x))))

  ; stream-iterate: apply f repeatedly: x, f(x), f(f(x)), ...
  (define (stream-iterate f x)
    (StreamCons x (lambda () (stream-iterate f (f x)))))

  (define (stream->list s)
    (if (stream-empty? s) '()
        (cons (stream-head s) (stream->list (stream-tail s)))))

  (define (list->stream lst)
    (if (null? lst) (StreamEmpty)
        (StreamCons (first lst)
                    (lambda () (list->stream (rest lst))))))

  (define (stream-zip s1 s2)
    (if (or (stream-empty? s1) (stream-empty? s2)) (StreamEmpty)
        (StreamCons (Pair (stream-head s1) (stream-head s2))
                    (lambda () (stream-zip (stream-tail s1)
                                           (stream-tail s2))))))

  (define (stream-append s1 s2)
    (if (stream-empty? s1) s2
        (StreamCons (stream-head s1)
                    (lambda () (stream-append (stream-tail s1) s2)))))

  ; ── Utility combinators ──────────────────────────────────────────────
  (define (identity x) x)
  (define (const x) (lambda (_) x))
  (define (flip f) (lambda (a b) (f b a)))
  (define (compose f g) (lambda (x) (f (g x))))

) ; end module Types

(open Types)
