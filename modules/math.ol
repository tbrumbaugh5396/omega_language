; std/math.ol — Math constants and functions

(module Math
  (export pi tau e square cube min max abs clamp even? odd? fib factorial)

  (define pi 3.141592653589793)
  (define tau (* 2 pi))
  (define e 2.718281828459045)

  (define (square x) (* x x))
  (define (cube x) (* x x x))

  (define (min a b) (if (< a b) a b))
  (define (max a b) (if (> a b) a b))
  (define (abs x) (if (< x 0) (- 0 x) x))

  (define (clamp x lo hi)
    (max lo (min x hi)))

  (define (even? n) (= (mod n 2) 0))
  (define (odd? n) (not (even? n)))

  (define (fib n)
    (define (go n a b)
      (if (= n 0) a (go (- n 1) b (+ a b))))
    (go n 0 1))

  (define (factorial n)
    (define (go n acc)
      (if (= n 0) acc (go (- n 1) (* acc n))))
    (go n 1)))