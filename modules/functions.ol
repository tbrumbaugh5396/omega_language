;; modules/functions - a module for functions

(module Functions

  (export
    ; Function utilities
    pipe thread-first thread-last memoize-fn)

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

) ; end module Functions

(open Functions)