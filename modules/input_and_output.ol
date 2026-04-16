(module IO
  (export read-file write-file exists? list-dir delete-file)

  (define (read-file path)
    (py-eval (string-append "open('" path "', 'r').read()")))

  (define (write-file path content)
    (py-exec (string-append "open('" path "', 'w').write(" (py-repr content) ")")))

  (define (exists? path)
    (py-eval (string-append "os.path.exists('" path "')")))

  (define (list-dir path)
    (py-eval (string-append "os.listdir('" path "')")))
    
  (define (delete-file path)
    (py-exec (string-append "os.remove('" path "')"))))