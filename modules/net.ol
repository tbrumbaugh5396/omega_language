(module Net
  (export get-json)
  (define (get-json url)
    (py-eval (string-append "requests.get('" url "').json()"))))