(module Random
  (export float int choice shuffle)

  (define (float) (py-eval "random.random()"))
  
  (define (int lo hi) 
    (py-eval (string-append "random.randint(" (number->string lo) "," (number->string hi) ")")))

  (define (choice lst)
    (py-eval (string-append "random.choice(" (py-repr lst) ")")))

  (define (shuffle lst)
    (py-eval (string-append "random.sample(" (py-repr lst) ", len(" (py-repr lst) "))"))))