;; modules/string.ol — String manipulation

(module String
  (export join split contains? starts-with? ends-with?
    ; String utilities
    str-join str-split-lines str-trim str-starts-with str-ends-with
    str-pad-left str-pad-right str-repeat str-contains
  )

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