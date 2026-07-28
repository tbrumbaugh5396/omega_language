;; modules/list.ol — List manipulation utilities

(module List
  (export length reverse append take drop zip flatten any? all?
    ; List utilities
    list-last list-init list-flatten list-zip list-unzip
    list-group-by list-partition list-range
    list-take list-drop list-take-while list-drop-while
    list-any list-all list-find list-find-index
    list-sum list-product list-min list-max list-mean
    list-unique list-count list-intersect list-union list-diff
  )

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

  ; ── List utilities ───────────────────────────────────────────────────


  (define (list-last lst)
    (if (null? (rest lst)) (first lst)
        (list-last (rest lst))))

  (define (list-init lst)
    (if (null? (rest lst)) '()
        (cons (first lst) (list-init (rest lst)))))

  (define (list-flatten lst)
    (cond ((null? lst) '())
          ((list? (first lst))
           (append (list-flatten (first lst)) (list-flatten (rest lst))))
          (else (cons (first lst) (list-flatten (rest lst))))))

  (define (list-zip a b)
    (if (or (null? a) (null? b)) '()
        (cons (list (first a) (first b))
              (list-zip (rest a) (rest b)))))

  (define (list-unzip pairs)
    (if (null? pairs)
        (list '() '())
        (let* ((rest-unzipped (list-unzip (rest pairs)))
               (first-pair    (first pairs)))
          (list (cons (first first-pair) (first rest-unzipped))
                (cons (second first-pair) (second rest-unzipped))))))

  (define (list-group-by key-fn lst)
    ; Returns alist of (key . items)
    (fold (lambda (acc item)
            (let* ((k   (key-fn item))
                   (grp (alist-get k acc '())))
              (alist-set k (append grp (list item)) acc)))
          '() lst))

  (define (list-partition pred lst)
    (list (filter pred lst)
          (filter (lambda (x) (not (pred x))) lst)))

  (define (list-range start end)
    (if (>= start end) '()
        (cons start (list-range (+ start 1) end))))

  (define (list-take n lst)
    (if (or (= n 0) (null? lst)) '()
        (cons (first lst) (list-take (- n 1) (rest lst)))))

  (define (list-drop n lst)
    (if (or (= n 0) (null? lst)) lst
        (list-drop (- n 1) (rest lst))))

  (define (list-take-while pred lst)
    (if (or (null? lst) (not (pred (first lst)))) '()
        (cons (first lst) (list-take-while pred (rest lst)))))

  (define (list-drop-while pred lst)
    (if (or (null? lst) (not (pred (first lst)))) lst
        (list-drop-while pred (rest lst))))

  (define (list-any pred lst)
    (and (not (null? lst))
         (or (pred (first lst)) (list-any pred (rest lst)))))

  (define (list-all pred lst)
    (or (null? lst)
        (and (pred (first lst)) (list-all pred (rest lst)))))

  (define (list-find pred lst)
    (cond ((null? lst) None)
          ((pred (first lst)) (Some (first lst)))
          (else (list-find pred (rest lst)))))

  (define (list-find-index pred lst)
    (letrec ((go (lambda (i l)
                   (cond ((null? l) None)
                         ((pred (first l)) (Some i))
                         (else (go (+ i 1) (rest l)))))))
      (go 0 lst)))

  (define (list-sum lst) (fold + 0 lst))
  (define (list-product lst) (fold * 1 lst))

  (define (list-min lst)
    (fold (lambda (acc x) (if (< x acc) x acc)) (first lst) (rest lst)))

  (define (list-max lst)
    (fold (lambda (acc x) (if (> x acc) x acc)) (first lst) (rest lst)))

  (define (list-mean lst)
    (if (null? lst) 0
        (/ (list-sum lst) (length lst))))

  (define (list-unique lst)
    (letrec ((go (lambda (seen remaining)
                   (if (null? remaining) '()
                       (let ((x (first remaining)))
                         (if (in x seen)
                             (go seen (rest remaining))
                             (cons x (go (cons x seen) (rest remaining)))))))))
      (go '() lst)))

  (define (list-count pred lst)
    (fold (lambda (acc x) (if (pred x) (+ acc 1) acc)) 0 lst))

  (define (list-intersect a b)
    (filter (lambda (x) (in x b)) a))

  (define (list-union a b)
    (append a (filter (lambda (x) (not (in x a))) b)))

  (define (list-diff a b)
    (filter (lambda (x) (not (in x b))) a))