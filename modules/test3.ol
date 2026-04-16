; std/test.ol — Minimal testing framework

(module Test
  (export assert-equal assert-true describe it run-tests)

  (define *test-passes* 0)
  (define *test-fails* 0)

  (define (assert-equal expected actual msg)
    (if (equal? expected actual)
        (begin
          (set! *test-passes* (+ *test-passes* 1))
          (print (string-append "  [PASS] " msg)))
        (begin
          (set! *test-fails* (+ *test-fails* 1))
          (print (string-append "  [FAIL] " msg " (Expected: " expected ", Got: " actual ")")))))

  (define (assert-true actual msg)
    (assert-equal true actual msg))

  (define (describe suite-name thunk)
    (print (string-append "\n=== " suite-name " ==="))
    (thunk))

  (define (it test-name thunk)
    (print (string-append "\n- " test-name))
    (thunk))

  (define (run-tests)
    (print "\n======================")
    (print (string-append "Tests complete. Passed: " *test-passes* " Failed: " *test-fails*))
    (set! *test-passes* 0)
    (set! *test-fails* 0)))