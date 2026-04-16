(module Net
  (export get get-json post download)

  (define _bootstrapped false)
  (define (ensure-req)
    (if _bootstrapped None
        (begin 
          (py-exec "import requests")
          (set! _bootstrapped true))))

  (define (get url)
    (ensure-req)
    (py-eval (string-append "requests.get('" url "').text")))

  (define (get-json url)
    (ensure-req)
    (py-eval (string-append "requests.get('" url "').json()")))

  (define (post url data-dict)
    (ensure-req)
    (py-eval (string-append "requests.post('" url "', json=" (py-repr data-dict) ").text")))

  (define (download url path)
    (ensure-req)
    (py-exec (string-append "open('" path "', 'wb').write(requests.get('" url "').content)"))))