; std/monad.ol — Maybe and Result types

(module Monad
  (export Just Nothing just? nothing? from-just 
          Ok Err ok? err? unwrap)

  ; --- Maybe ---
  (define (Just x)    (list 'Just x))
  (define Nothing     (list 'Nothing))
  (define (just? m)   (= (first m) 'Just))
  (define (nothing? m)(= (first m) 'Nothing))
  (define (from-just m default-val) (if (just? m) (second m) default-val))

  ; --- Result ---
  (define (Ok x)      (list 'Ok x))
  (define (Err msg)   (list 'Err msg))
  (define (ok? r)     (= (first r) 'Ok))
  (define (err? r)    (= (first r) 'Err))
  (define (unwrap r)  (if (ok? r) (second r) (print (string-append "Unwrap failed: " (second r))))))