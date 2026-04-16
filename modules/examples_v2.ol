; =============================================================================
; OMEGA LISP — Example Code
; =============================================================================
; Run any block interactively by pasting it into the REPL.
; =============================================================================

; Explicit export list — controls what (import "examples_v2.ol" e) surfaces.
; Only reusable library functions and constants are exported.
; Demo expressions, internal helpers, and test values are kept private.
(export
  ; constants
  pi tau
  ; core math
  square cube circle-area clamp make-adder
  ; sequences
  fizzbuzz sum-of-squares dot-product
  ; recursion
  fib fib-tail factorial
  ; BST
  bst-insert bst-contains? bst-inorder list->bst
  ; Maybe monad
  Just Nothing just? nothing? from-just
  maybe-map maybe-bind maybe-return safe-div safe-sqrt maybe-pipeline
  ; Result monad
  Ok Err ok? err? unwrap unwrap-err
  result-map result-bind checked-div result-all
  ; Peano naturals
  Zero Succ zero? pred nat->int int->nat nat-add nat-mul
  ; Linked list
  LNil LCons lnil? lcons? lhead ltail
  list->linked linked->list linked-map linked-filter linked-length
  ; Streams
  SCons stream-head stream-tail stream-from stream-fib
  stream-take stream-map stream-filter stream-nth
  naturals fibs evens squares
  ; Rose tree
  Leaf Node leaf? tree-val tree-kids
  tree-map tree-fold tree-depth sample-tree
  ; State monad
  state-return state-get state-put state-modify state-bind run-state
  count-and-increment three-counts
  ; Writer monad
  writer-return writer-bind writer-tell writer-run
  ; Reader monad
  reader-return reader-bind reader-ask reader-run reader-local
  ; Validated / multi-error
  validate-all
  ; Expression evaluator
  Num Add Mul Neg Div eval-expr
)


; ---------------------------------------------------------------------------
; 1. BASICS
; ---------------------------------------------------------------------------

(+ 1 2 3)                          ; => 6
(* 2 (+ 3 4))                      ; => 14
(/ 10 4)                           ; => 2.5
(mod 17 5)                         ; => 2
(** 2 10)                          ; => 1024

"hello world"
(string-append "foo" "bar")        ; => foobar
(string-length "omega")            ; => 5
(string-upcase "lisp")             ; => LISP


; ---------------------------------------------------------------------------
; 2. VARIABLES & FUNCTIONS
; ---------------------------------------------------------------------------

(define pi 3.14159)
(define tau (* 2 pi))

(define (square x) (* x x))
(define (cube   x) (* x x x))
(define (circle-area r) (* pi (square r)))

(square 5)           ; => 25
(circle-area 3)      ; => 28.274...

(define (clamp x lo hi)
  (cond ((< x lo) lo)
        ((> x hi) hi)
        (else     x)))

(clamp 15 0 10)      ; => 10
(clamp -5 0 10)      ; => 0


; ---------------------------------------------------------------------------
; 3. LAMBDAS & HIGHER-ORDER FUNCTIONS
; ---------------------------------------------------------------------------

(define (make-adder n) (lambda (x) (+ x n)))
(define add5  (make-adder 5))
(define add10 (make-adder 10))

(add5 3)             ; => 8
(add10 3)            ; => 13

(map square '(1 2 3 4 5))                          ; => [1 4 9 16 25]
(filter (lambda (x) (= (mod x 2) 0)) '(1 2 3 4 5 6))  ; => [2 4 6]
(reduce + '(1 2 3 4 5))                            ; => 15


; ---------------------------------------------------------------------------
; 4. CONDITIONALS
; ---------------------------------------------------------------------------

(define (fizzbuzz n)
  (cond ((= (mod n 15) 0) "FizzBuzz")
        ((= (mod n 3)  0) "Fizz")
        ((= (mod n 5)  0) "Buzz")
        (else             (number->string n))))

(map fizzbuzz (range 1 16))
; => [1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz]


; ---------------------------------------------------------------------------
; 5. RECURSION & TAIL-CALL OPTIMISATION
; ---------------------------------------------------------------------------

(define (fib n)
  (if (<= n 1) n (+ (fib (- n 1)) (fib (- n 2)))))

(fib 10)   ; => 55

(define (fib-tail n)
  (define (go n a b)
    (if (= n 0) a (go (- n 1) b (+ a b))))
  (go n 0 1))

(fib-tail 30)   ; => 832040

(define (factorial n)
  (define (go n acc)
    (if (= n 0) acc (go (- n 1) (* acc n))))
  (go n 1))

(factorial 10)  ; => 3628800


; ---------------------------------------------------------------------------
; 6. LET FORMS
; ---------------------------------------------------------------------------

(let ((x 10) (y 20)) (+ x y))      ; => 30

(let* ((x 5) (y (* x 2)) (z (+ x y))) z)   ; => 15

(letrec ((even? (lambda (n) (if (= n 0) true  (odd?  (- n 1)))))
         (odd?  (lambda (n) (if (= n 0) false (even? (- n 1))))))
  (list (even? 4) (odd? 7)))        ; => [true true]


; ---------------------------------------------------------------------------
; 7. LIST OPERATIONS
; ---------------------------------------------------------------------------

(define nums '(3 1 4 1 5 9 2 6))

(length  nums)           ; => 8
(first   nums)           ; => 3
(rest    nums)           ; => [1 4 1 5 9 2 6]
(reverse nums)           ; => [6 2 9 5 1 4 1 3]
(sort    nums)           ; => [1 1 2 3 4 5 6 9]
(nth     nums 4)         ; => 5

(cons 0 '(1 2 3))                  ; => [0 1 2 3]
(append '(1 2) '(3 4) '(5))       ; => [1 2 3 4 5]
(flatten '(1 (2 3) (4 (5))))       ; => [1 2 3 4 5]

(define (sum-of-squares lst)
  (reduce + (map square lst)))

(sum-of-squares '(1 2 3 4 5))      ; => 55

(zip-lists '(a b c) '(1 2 3))      ; => [[a 1] [b 2] [c 3]]

(define (dot-product u v)
  (reduce + (map (lambda (p) (* (first p) (second p)))
                 (zip-lists u v))))

(dot-product '(1 2 3) '(4 5 6))    ; => 32


; ---------------------------------------------------------------------------
; 8. QUASIQUOTE
; ---------------------------------------------------------------------------

(define x 42)
`(the answer is ,x)                ; => [the answer is 42]

(define extras '(4 5 6))
`(1 2 3 ,@extras 7)               ; => [1 2 3 4 5 6 7]

(define (template op a b) `(,op ,a ,b))
(evaluate (template '+ 1 2))       ; => 3


; ---------------------------------------------------------------------------
; 9. MACROS
; ---------------------------------------------------------------------------

(register-macro! defmacro
  (name params body)
  (list 'register-macro! (list 'quote name) params body))

(defmacro inc (n) `(+ ,n 1))
(defmacro dec (n) `(- ,n 1))

(inc 5)    ; => 6
(dec 5)    ; => 4

(defmacro unless (cond body) `(if (not ,cond) ,body None))
(defmacro when   (cond body) `(if ,cond ,body None))

(unless false "executed")          ; => executed
(when   true  "yes")              ; => yes

; Macros short-circuit; lambdas do not:
(defmacro my-and (a b) `(if ,a ,b false))
(my-and false (error! "never runs"))  ; => false

; swap! — gensym prevents variable capture
(defmacro swap! (a b)
  (let ((tmp (gensym "tmp")))
    `(let ((,tmp ,a))
       (set! ,a ,b)
       (set! ,b ,tmp))))

(define p 10) (define q 20)
(swap! p q)
(list p q)   ; => [20 10]

(defmacro dotimes (var n body)
  `(let ((,var 0))
     (while (< ,var ,n)
       (begin ,body (set! ,var (inc ,var))))))

(dotimes i 5 (print i))   ; prints 0 1 2 3 4

(expand '(inc 42))         ; => [+ 42 1]
(expand '(when true "y"))  ; => [if true y None]


; ---------------------------------------------------------------------------
; 10. MODULES
; ---------------------------------------------------------------------------

(module Math
  (define (square x) (* x x))
  (define (cube   x) (* x x x))
  (define pi 3.14159265358979))

Math.pi            ; => 3.14159...
(Math.square 4)    ; => 16

(open Math)
(square 5)         ; => 25


; ---------------------------------------------------------------------------
; 11. READER MACROS
; ---------------------------------------------------------------------------

(register-reader-macro! '~
  (lambda (stream) (list 'inc (read stream))))

~ 5     ; => 6
~ ~ 5   ; => 7

(register-reader-macro! '#
  (lambda (stream) (list 'length (read stream))))

# '(1 2 3 4 5)    ; => 5


; ---------------------------------------------------------------------------
; 12. PERSISTENCE
; ---------------------------------------------------------------------------

(save-image "my-session" (find-root))
; => "a3f8c12d4e5b6789-my-session"

(set-prelude! "a3f8c12d4e5b6789-my-session")
; On next boot all macros, functions, reader macros are restored.

(omega-home)    ; => ~/.omega
(store-path)    ; => ~/.omega/store
(view-config)   ; => {prelude_file: ..., prelude_enabled: true}


; ---------------------------------------------------------------------------
; 13. CAPABILITIES
; ---------------------------------------------------------------------------

(define io-cap (new-capability "io"))
(grant-capability io-cap)

(with-capability io-cap
  (print "I have io permission"))


; ---------------------------------------------------------------------------
; 14. BINARY SEARCH TREE
; ---------------------------------------------------------------------------

; BST node: (value left right) — None is the empty tree

(define (bst-insert tree val)
  (cond ((null? tree)          (list val None None))
        ((< val (first tree))  (list (first tree) (bst-insert (second tree) val) (nth tree 2)))
        ((> val (first tree))  (list (first tree) (second tree) (bst-insert (nth tree 2) val)))
        (else tree)))

(define (bst-contains? tree val)
  (cond ((null? tree)          false)
        ((= val (first tree))  true)
        ((< val (first tree))  (bst-contains? (second tree) val))
        (else                  (bst-contains? (nth tree 2) val))))

(define (bst-inorder tree)
  (if (null? tree) '()
      (append (bst-inorder (second tree))
              (list (first tree))
              (bst-inorder (nth tree 2)))))

(define (list->bst lst) (reduce bst-insert lst None))

(define my-tree (list->bst '(5 3 7 1 4 6 8 2)))

(bst-contains? my-tree 4)    ; => true
(bst-contains? my-tree 9)    ; => false
(bst-inorder   my-tree)      ; => [1 2 3 4 5 6 7 8]


; =============================================================================
; PART II — FUNCTIONAL PROGRAMMING TYPES
; (Haskell-style ADTs encoded in Omega Lisp)
; =============================================================================
;
; Convention: all algebraic types are tagged lists.
;   (Tag field1 field2 ...)
; Pattern matching is done with cond + predicates.
; =============================================================================


; ---------------------------------------------------------------------------
; A. MAYBE  (Haskell: Maybe a = Nothing | Just a)
; ---------------------------------------------------------------------------
; Represents an optional value — either a value exists (Just) or it doesn't.

(define (Just x)    (list 'Just x))
(define (Nothing)   (list 'Nothing))

(define (just?    m) (= (first m) 'Just))
(define (nothing? m) (= (first m) 'Nothing))
(define (from-just m default)
  (if (just? m) (second m) default))

; Functor: fmap over Maybe
(define (maybe-map f m)
  (if (just? m) (Just (f (second m))) (Nothing)))

; Monad: chain Maybe computations
(define (maybe-bind m f)
  (if (just? m) (f (second m)) (Nothing)))

(define (maybe-return x) (Just x))

; Safe arithmetic
(define (safe-div a b)
  (if (= b 0) (Nothing) (Just (/ a b))))

(define (safe-sqrt x)
  (if (< x 0) (Nothing) (Just (sqrt x))))

(safe-div  10 2)              ; => [Just 5.0]
(safe-div  10 0)              ; => [Nothing]
(safe-sqrt  9)                ; => [Just 3.0]
(safe-sqrt -1)                ; => [Nothing]

(from-just (safe-div 10 2) 0) ; => 5.0
(from-just (safe-div 10 0) 0) ; => 0

; Chaining with bind
(maybe-bind (safe-div 100 5)
  (lambda (x) (safe-sqrt x)))
; => [Just 4.47...]

(maybe-bind (safe-div 100 0)
  (lambda (x) (safe-sqrt x)))
; => [Nothing]

; maybe-pipeline: chain a list of (a -> Maybe b) functions
(define (maybe-pipeline val fns)
  (reduce maybe-bind (map (lambda (f) f) fns) (Just val)))


; ---------------------------------------------------------------------------
; B. RESULT  (Haskell: Either e a = Left e | Right a)
; ---------------------------------------------------------------------------
; Represents success (Ok) or failure (Err) with a message.

(define (Ok  value)   (list 'Ok  value))
(define (Err message) (list 'Err message))

(define (ok?  r) (= (first r) 'Ok))
(define (err? r) (= (first r) 'Err))
(define (unwrap r default) (if (ok? r) (second r) default))
(define (unwrap-err r)     (if (err? r) (second r) None))

(define (result-map f r)
  (if (ok? r) (Ok (f (second r))) r))

(define (result-bind r f)
  (if (ok? r) (f (second r)) r))

; Validated division
(define (checked-div a b)
  (cond ((not (integer? b))  (Err "divisor must be integer"))
        ((= b 0)             (Err "division by zero"))
        (else                (Ok (/ a b)))))

(checked-div 10 2)   ; => [Ok 5.0]
(checked-div 10 0)   ; => [Err division by zero]

; Chain results
(result-bind (checked-div 100 5)
  (lambda (x) (if (> x 10) (Ok x) (Err "too small"))))
; => [Ok 20.0]

; Collect errors
(define (result-all results)
  (reduce (lambda (acc r)
            (cond ((err? acc) acc)
                  ((err? r)   r)
                  (else       (Ok (append (list (unwrap acc None)) (list (second r)))))))
          results
          (Ok '())))

(result-all (list (Ok 1) (Ok 2) (Ok 3)))          ; => [Ok [1 2 3]]
(result-all (list (Ok 1) (Err "bad") (Ok 3)))      ; => [Err bad]


; ---------------------------------------------------------------------------
; C. PEANO NATURAL NUMBERS
; (Haskell: Nat = Zero | Succ Nat)
; ---------------------------------------------------------------------------
; Church-style proof that natural numbers arise from pure structure.

(define (Zero)    (list 'Zero))
(define (Succ n)  (list 'Succ n))

(define (zero? n) (= (first n) 'Zero))
(define (pred  n) (if (zero? n) (Zero) (second n)))

; Convert to/from regular integers
(define (nat->int n)
  (if (zero? n) 0 (+ 1 (nat->int (pred n)))))

(define (int->nat k)
  (if (= k 0) (Zero) (Succ (int->nat (- k 1)))))

; Arithmetic on Peano nats
(define (nat-add a b)
  (if (zero? b) a (Succ (nat-add a (pred b)))))

(define (nat-mul a b)
  (if (zero? b) (Zero) (nat-add a (nat-mul a (pred b)))))

(define (nat-eq? a b)
  (cond ((and (zero? a) (zero? b)) true)
        ((or  (zero? a) (zero? b)) false)
        (else (nat-eq? (pred a) (pred b)))))

(define one   (int->nat 1))
(define two   (int->nat 2))
(define three (int->nat 3))

(nat->int (nat-add two three))   ; => 5
(nat->int (nat-mul two three))   ; => 6
(nat-eq? (nat-add one two) three) ; => true


; ---------------------------------------------------------------------------
; D. LINKED LIST  (Haskell: List a = Nil | Cons a (List a))
; ---------------------------------------------------------------------------

(define (Nil)        (list 'Nil))
(define (Cons x xs)  (list 'Cons x xs))

(define (nil?  xs) (= (first xs) 'Nil))
(define (head  xs) (second xs))
(define (tail  xs) (third  xs))

; Convert
(define (list->linked xs)
  (if (null? xs) (Nil)
      (Cons (first xs) (list->linked (rest xs)))))

(define (linked->list xs)
  (if (nil? xs) '()
      (cons (head xs) (linked->list (tail xs)))))

; Functor / fold
(define (linked-map f xs)
  (if (nil? xs) (Nil) (Cons (f (head xs)) (linked-map f (tail xs)))))

(define (linked-fold f acc xs)
  (if (nil? xs) acc (linked-fold f (f acc (head xs)) (tail xs))))

(define (linked-filter pred xs)
  (cond ((nil? xs)           (Nil))
        ((pred (head xs))    (Cons (head xs) (linked-filter pred (tail xs))))
        (else                (linked-filter pred (tail xs)))))

(define ll (list->linked '(1 2 3 4 5)))

(linked->list (linked-map (lambda (x) (* x x)) ll))
; => [1 4 9 16 25]

(linked-fold + 0 ll)
; => 15

(linked->list (linked-filter (lambda (x) (> x 2)) ll))
; => [3 4 5]


; ---------------------------------------------------------------------------
; E. LAZY STREAMS  (Haskell: infinite lists via thunks)
; ---------------------------------------------------------------------------
; A Stream is (SCons head thunk) where thunk is a zero-arg lambda.
; Forcing the thunk gives the next Stream.

(define (SCons head tail-thunk) (list 'SCons head tail-thunk))
(define (stream-head s) (second s))
(define (stream-tail s) ((third s)))     ; force the thunk

(defmacro lazy (expr) `(lambda () ,expr))

; Infinite stream of a constant value
(define (stream-repeat x)
  (SCons x (lazy (stream-repeat x))))

; Infinite stream of integers from n
(define (stream-from n)
  (SCons n (lazy (stream-from (+ n 1)))))

; Infinite stream of Fibonacci numbers
(define (stream-fib a b)
  (SCons a (lazy (stream-fib b (+ a b)))))

; Take first n elements
(define (stream-take n s)
  (if (= n 0) '()
      (cons (stream-head s)
            (stream-take (- n 1) (stream-tail s)))))

; Map over a stream
(define (stream-map f s)
  (SCons (f (stream-head s))
         (lazy (stream-map f (stream-tail s)))))

; Filter a stream (always finds next matching element)
(define (stream-filter pred s)
  (if (pred (stream-head s))
      (SCons (stream-head s)
             (lazy (stream-filter pred (stream-tail s))))
      (stream-filter pred (stream-tail s))))

; nth element (0-indexed)
(define (stream-nth n s)
  (if (= n 0) (stream-head s)
      (stream-nth (- n 1) (stream-tail s))))

; Infinite naturals, fibs, evens
(define naturals (stream-from 0))
(define fibs     (stream-fib 0 1))
(define evens    (stream-filter (lambda (x) (= (mod x 2) 0)) naturals))
(define squares  (stream-map square naturals))

(stream-take 8 naturals)     ; => [0 1 2 3 4 5 6 7]
(stream-take 8 fibs)         ; => [0 1 1 2 3 5 8 13]
(stream-take 6 evens)        ; => [0 2 4 6 8 10]
(stream-take 6 squares)      ; => [0 1 4 9 16 25]
(stream-nth 10 fibs)         ; => 55


; ---------------------------------------------------------------------------
; F. ROSE TREE  (Haskell: Tree a = Leaf | Node a [Tree a])
; ---------------------------------------------------------------------------

(define (Leaf)          (list 'Leaf))
(define (Node val kids) (list 'Node val kids))

(define (leaf? t) (= (first t) 'Leaf))
(define (tree-val  t) (second t))
(define (tree-kids t) (third  t))

(define (tree-map f t)
  (if (leaf? t) (Leaf)
      (Node (f (tree-val t))
            (map (lambda (kid) (tree-map f kid)) (tree-kids t)))))

(define (tree-fold f acc t)
  (if (leaf? t) acc
      (fold (lambda (a kid) (tree-fold f a kid))
            (f acc (tree-val t))
            (tree-kids t))))

(define (tree-depth t)
  (if (leaf? t) 0
      (+ 1 (reduce max (map tree-depth (tree-kids t)) 0))))

(define sample-tree
  (Node 1 (list (Node 2 (list (Node 4 '()) (Node 5 '())))
                (Node 3 (list (Node 6 '()))))))

(tree-fold + 0 sample-tree)    ; => 21  (sum of all nodes)
(tree-depth sample-tree)       ; => 2


; ---------------------------------------------------------------------------
; G. STATE MONAD  (threading mutable state through pure functions)
; ---------------------------------------------------------------------------
; State s a = s -> (a, s)
; The value is a lambda that takes a state and returns [result new-state].

(define (state-return x)       (lambda (s) (list x s)))
(define (state-get)            (lambda (s) (list s s)))
(define (state-put new-s)      (lambda (s) (list None new-s)))
(define (state-modify f)       (lambda (s) (list None (f s))))

(define (state-bind m f)
  (lambda (s)
    (let ((result (m s)))
      ((f (first result)) (second result)))))

(define (run-state m initial) (m initial))

; Example: counter that auto-increments
(define count-and-increment
  (state-bind (state-get)
    (lambda (n)
      (state-bind (state-put (+ n 1))
        (lambda (_) (state-return n))))))

(run-state count-and-increment 0)    ; => [0 1]  (got 0, state now 1)
(run-state count-and-increment 5)    ; => [5 6]  (got 5, state now 6)

; Run three increments in sequence
(define three-counts
  (state-bind count-and-increment
    (lambda (a)
      (state-bind count-and-increment
        (lambda (b)
          (state-bind count-and-increment
            (lambda (c)
              (state-return (list a b c)))))))))

(run-state three-counts 0)    ; => [[0 1 2] 3]


; ---------------------------------------------------------------------------
; H. WRITER MONAD  (accumulate a log alongside computation)
; ---------------------------------------------------------------------------
; Writer w a = (a, w)  where w is a monoid (here: a list of strings)

(define (writer-return x)  (list x '()))
(define (writer-tell msg)  (list None (list msg)))

(define (writer-bind m f)
  (let ((val (first m))
        (log (second m)))
    (let ((result (f val)))
      (list (first result)
            (append log (second result))))))

(define (run-writer m) m)   ; already a pair

; Traced factorial
(define (traced-factorial n)
  (if (= n 0)
      (writer-bind (writer-tell "base case: 1") (lambda (_) (writer-return 1)))
      (writer-bind (traced-factorial (- n 1))
        (lambda (prev)
          (writer-bind (writer-tell (string-append "* " (number->string n)))
            (lambda (_) (writer-return (* prev n))))))))

(run-writer (traced-factorial 4))
; => [24  [base case: 1  * 1  * 2  * 3  * 4]]


; ---------------------------------------------------------------------------
; I. ASSOCIATION LIST / DICTIONARY
; ---------------------------------------------------------------------------

(define (dict-empty)       '())
(define (dict-set d k v)   (cons (list k v) (dict-remove d k)))
(define (dict-remove d k)  (filter (lambda (pair) (not (= (first pair) k))) d))
(define (dict-get d k)
  (let ((found (filter (lambda (pair) (= (first pair) k)) d)))
    (if (null? found) (Nothing) (Just (second (first found))))))
(define (dict-keys d)  (map first d))
(define (dict-vals d)  (map second d))

(define db (dict-empty))
(define db (dict-set db 'name   "Alice"))
(define db (dict-set db 'age    30))
(define db (dict-set db 'lang   "Lisp"))

(dict-get db 'name)      ; => [Just Alice]
(dict-get db 'missing)   ; => [Nothing]
(dict-keys db)           ; => [name age lang]


; ---------------------------------------------------------------------------
; J. TYPECLASSES VIA DISPATCH DICTIONARIES
; ---------------------------------------------------------------------------
; Omega has no built-in typeclasses, but we can simulate them with
; a dictionary of method implementations — an "instance dictionary".

; Typeclass Eq: methods (equal? not-equal?)
(define (make-eq equal-fn)
  (list (list 'equal?     equal-fn)
        (list 'not-equal? (lambda (a b) (not (equal-fn a b))))))

; Typeclass Ord: methods (compare less? greater? between?)
(define (make-ord cmp-fn)
  (list (list 'compare  cmp-fn)
        (list 'less?    (lambda (a b) (= (cmp-fn a b) -1)))
        (list 'greater? (lambda (a b) (= (cmp-fn a b)  1)))
        (list 'between? (lambda (x lo hi) (and (not (= (cmp-fn x lo) -1))
                                               (not (= (cmp-fn x hi)  1)))))))

; Instance for integers
(define int-eq
  (make-eq (lambda (a b) (= a b))))

(define int-ord
  (make-ord (lambda (a b) (cond ((< a b) -1) ((> a b) 1) (else 0)))))

(define (tc-method dict name)
  (second (first (filter (lambda (p) (= (first p) name)) dict))))

(define int-less?    (tc-method int-ord 'less?))
(define int-greater? (tc-method int-ord 'greater?))
(define int-between? (tc-method int-ord 'between?))

(int-less?    3 5)         ; => true
(int-greater? 5 3)         ; => true
(int-between? 4 1 10)      ; => true
(int-between? 0 1 10)      ; => false


; ---------------------------------------------------------------------------
; K. OPTION PARSING / VALIDATION PIPELINE
; ---------------------------------------------------------------------------

(define (validate-positive x)
  (if (> x 0) (Ok x) (Err "must be positive")))

(define (validate-even x)
  (if (= (mod x 2) 0) (Ok x) (Err "must be even")))

(define (validate-small x)
  (if (< x 100) (Ok x) (Err "must be < 100")))

(define (validate-all x validators)
  (reduce result-bind validators (Ok x)))

(validate-all  4  (list validate-positive validate-even validate-small))  ; => [Ok 4]
(validate-all -1  (list validate-positive validate-even validate-small))  ; => [Err must be positive]
(validate-all  3  (list validate-positive validate-even validate-small))  ; => [Err must be even]
(validate-all 200 (list validate-positive validate-even validate-small))  ; => [Err must be < 100]


; ---------------------------------------------------------------------------
; L. PUTTING IT TOGETHER — type-safe expression evaluator
; ---------------------------------------------------------------------------

; A tiny expression language: Num | Add | Mul | Div | Neg
(define (Num n)     (list 'Num n))
(define (Add e1 e2) (list 'Add e1 e2))
(define (Mul e1 e2) (list 'Mul e1 e2))
(define (Div e1 e2) (list 'Div e1 e2))
(define (Neg e)     (list 'Neg e))

(define (eval-expr e)
  (let ((tag (first e)))
    (cond
      ((= tag 'Num) (Ok (second e)))
      ((= tag 'Neg)
       (result-map (lambda (v) (- v)) (eval-expr (second e))))
      ((= tag 'Add)
       (result-bind (eval-expr (second e))
         (lambda (a) (result-map (lambda (b) (+ a b)) (eval-expr (third e))))))
      ((= tag 'Mul)
       (result-bind (eval-expr (second e))
         (lambda (a) (result-map (lambda (b) (* a b)) (eval-expr (third e))))))
      ((= tag 'Div)
       (result-bind (eval-expr (second e))
         (lambda (a)
           (result-bind (eval-expr (third e))
             (lambda (b) (checked-div a b))))))
      (else (Err (string-append "unknown tag: " (number->string tag)))))))

(eval-expr (Add (Num 3) (Mul (Num 4) (Num 5))))   ; => [Ok 23]
(eval-expr (Div (Num 10) (Num 0)))                 ; => [Err division by zero]
(eval-expr (Neg (Add (Num 1) (Num 2))))            ; => [Ok -3]
(eval-expr (Add (Div (Num 6) (Num 2))
                (Mul (Num 3) (Neg (Num 4)))))       ; => [Ok -9]
