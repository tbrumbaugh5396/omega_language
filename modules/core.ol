; std/core.ol — Core macros and higher-order functions

(module Core
  (export let not compose partial constantly identity)

  ; From bootstrap.omega
  (register-macro! defmacro (name params body)
    (list 'register-macro! (list 'quote name) params body))

  (defmacro let (bindings body)
    ((lambda (vars vals)
       (append (list (list 'lambda vars body)) vals))
     (map first bindings)
     (map second bindings)))

  ; Basic logic
  (define (not x) (if x false true))

  ; Functional Primitives
  (define (identity x) x)
  (define (constantly x) (lambda args x))

  (define (compose f g)
    (lambda (x) (f (g x))))

  (define (partial f arg)
    (lambda args (apply f (cons arg args))))

  (define (get-at obj key)
    (py-eval (string-append (py-repr obj) "[" (py-repr key) "]")))
)