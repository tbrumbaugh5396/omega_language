;; modules/debug.ol - a module for debugging

(module Debug
  (export
    ; Debug
    debug-print trace-val
  )
  ; ── Debug ────────────────────────────────────────────────────────────

  (define (debug-print label val)
    (print (string-append "[DEBUG] " label ": " (py-eval (string-append "repr(" (number->string 0) ")"))))
    val)

  (define (trace-val label val)
    (print (string-append label ": " (number->string val)))
    val)

) ; end module Debug

(open Debug)