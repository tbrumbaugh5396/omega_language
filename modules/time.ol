(module Time
  (export now sleep format-now)

  (define (now) (py-eval "time.time()"))
  
  (define (sleep ms) 
    (py-exec (string-append "time.sleep(" (number->string (/ ms 1000)) ")")))

  (define (format-now)
    (py-eval "time.strftime('%Y-%m-%d %H:%M:%S')")))