(module JSON
  (export parse stringify)
  
  (define (parse s)
    (py-eval (string-append "json.loads('" s "')")))
    
  (define (stringify obj)
    (py-eval (string-append "json.dumps(" (py-repr obj) ")"))))