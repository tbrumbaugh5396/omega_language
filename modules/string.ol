; std/string.ol — String manipulation

(module String
  (export join split contains? starts-with? ends-with?)

  (define (join sep strings)
    (if (null? strings) ""
        (reduce (lambda (acc s) (string-append acc sep s))
                (rest strings)
                (first strings))))

  ; Relies on Python interop for heavy lifting (assuming string-split exists in env)
  (define (split s sep)
    (string-split s sep))

  ; If string-contains? isn't in core, we implement via Python's `in` or regex
  (define (contains? s sub)
    (py-eval (string-append "'" sub "' in '" s "'")))

  (define (starts-with? s prefix)
    (py-eval (string-append "'" s "'.startswith('" prefix "')")))

  (define (ends-with? s suffix)
    (py-eval (string-append "'" s "'.endswith('" suffix "')"))))