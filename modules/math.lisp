(module LinearAlgebra
    (define dot-product 
        (lambda (a b)
            (if (null? a)
                0
                (+ (* (first a) (first b)) 
                   (dot-product (rest a) (rest b))))))

    (define matrix-identity-2x2 
        (list (list 1 0) (list 0 1))))

(module Vector
    (define magnitude 
        (lambda (v)
            (sqrt (LinearAlgebra.dot-product v v))))

    (define normalize 
        (lambda (v)
            (map (lambda (x) (/ x (magnitude v))) v))))

(module Constants
    (define-const PI 3.1415926535)
    (define-const E  2.7182818284))

(define fact 
    (lambda (n) 
        (if (= n 0) 1 (* n (fact (- n 1))))))