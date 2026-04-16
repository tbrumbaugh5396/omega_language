; std/list.ol — List manipulation utilities

(module List
  (export length reverse append take drop zip flatten any? all?)

  (define (length lst)
    (if (null? lst) 0 (+ 1 (length (rest lst)))))

  (define (reverse lst)
    (define (rev-acc l acc)
      (if (null? l) acc (rev-acc (rest l) (cons (first l) acc))))
    (rev-acc lst '()))

  (define (append l1 l2)
    (if (null? l1) l2 (cons (first l1) (append (rest l1) l2))))

  (define (take n lst)
    (if (or (= n 0) (null? lst)) '()
        (cons (first lst) (take (- n 1) (rest lst)))))

  (define (drop n lst)
    (if (or (= n 0) (null? lst)) lst
        (drop (- n 1) (rest lst))))

  (define (zip l1 l2)
    (if (or (null? l1) (null? l2)) '()
        (cons (list (first l1) (first l2)) 
              (zip (rest l1) (rest l2)))))

  (define (flatten lst)
    (cond ((null? lst) '())
          ((not (list? lst)) (list lst))
          (else (append (flatten (first lst)) (flatten (rest lst))))))

  (define (any? pred lst)
    (cond ((null? lst) false)
          ((pred (first lst)) true)
          (else (any? pred (rest lst)))))

  (define (all? pred lst)
    (cond ((null? lst) true)
          ((not (pred (first lst))) false)
          (else (all? pred (rest lst))))))