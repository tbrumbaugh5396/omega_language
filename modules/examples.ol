; =============================================================================
; OMEGA LISP — Example Code
; =============================================================================
; Run any block interactively by pasting it into the REPL (λ >).
; Or load this file as a module: (import "examples.ol")
; =============================================================================


; ---------------------------------------------------------------------------
; 1. BASICS — numbers, strings, booleans, arithmetic
; ---------------------------------------------------------------------------

(+ 1 2 3)           ; => 6
(* 2 (+ 3 4))       ; => 14
(/ 10 4)            ; => 2.5
(mod 17 5)          ; => 2
(** 2 10)           ; => 1024

"hello world"       ; => hello world
(string-append "foo" "bar")   ; => foobar
(string-length "omega")       ; => 5
(string-upcase "lisp")        ; => LISP


; ---------------------------------------------------------------------------
; 2. VARIABLES & FUNCTIONS
; ---------------------------------------------------------------------------

; Simple binding
(define pi 3.14159)
(define tau (* 2 pi))

; Function shorthand
(define (square x) (* x x))
(define (cube   x) (* x x x))
(define (circle-area r) (* pi (square r)))

(square 5)           ; => 25
(circle-area 3)      ; => 28.27431...

; Multi-arg, multi-expression body
(define (clamp x lo hi)
  (cond
    ((< x lo) lo)
    ((> x hi) hi)
    (else     x)))

(clamp 15 0 10)      ; => 10
(clamp -5 0 10)      ; => 0
(clamp  7 0 10)      ; => 7


; ---------------------------------------------------------------------------
; 3. LAMBDAS — first-class functions
; ---------------------------------------------------------------------------

(define add (lambda (a b) (+ a b)))
(define mul (lambda (a b) (* a b)))

; Higher-order: functions returning functions
(define (make-adder n)
  (lambda (x) (+ x n)))

(define add5  (make-adder 5))
(define add10 (make-adder 10))

(add5 3)    ; => 8
(add10 3)   ; => 13

; Passing functions as arguments
(map square '(1 2 3 4 5))        ; => [1 4 9 16 25]
(filter (lambda (x) (= (mod x 2) 0)) '(1 2 3 4 5 6))  ; => [2 4 6]
(reduce + '(1 2 3 4 5))          ; => 15


; ---------------------------------------------------------------------------
; 4. CONDITIONALS
; ---------------------------------------------------------------------------

(define (fizzbuzz n)
  (cond
    ((= (mod n 15) 0) "FizzBuzz")
    ((= (mod n 3)  0) "Fizz")
    ((= (mod n 5)  0) "Buzz")
    (else             (number->string n))))

(map fizzbuzz (range 1 16))
; => [1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz]


; ---------------------------------------------------------------------------
; 5. RECURSION & TAIL-CALL OPTIMISATION
; ---------------------------------------------------------------------------

; Classic recursive fibonacci (exponential — use letrec for mutual recursion)
(define (fib n)
  (if (<= n 1) n
      (+ (fib (- n 1)) (fib (- n 2)))))

(fib 10)   ; => 55

; Tail-recursive accumulator version (safe for large n)
(define (fib-tail n)
  (define (go n a b)
    (if (= n 0) a
        (go (- n 1) b (+ a b))))
  (go n 0 1))

(fib-tail 30)   ; => 832040

; Tail-recursive factorial
(define (factorial n)
  (define (go n acc)
    (if (= n 0) acc
        (go (- n 1) (* acc n))))
  (go n 1))

(factorial 10)  ; => 3628800


; ---------------------------------------------------------------------------
; 6. LET FORMS
; ---------------------------------------------------------------------------

; let  — parallel bindings (each binding sees the *outer* scope)
(let ((x 10)
      (y 20))
  (+ x y))            ; => 30

; let* — sequential bindings (each binding sees the previous)
(let* ((x 5)
       (y (* x 2))
       (z (+ x y)))
  z)                  ; => 15

; letrec — mutual recursion
(letrec ((even? (lambda (n) (if (= n 0) true  (odd?  (- n 1)))))
         (odd?  (lambda (n) (if (= n 0) false (even? (- n 1))))))
  (list (even? 4) (odd? 7)))    ; => [true true]


; ---------------------------------------------------------------------------
; 7. LIST OPERATIONS
; ---------------------------------------------------------------------------

(define nums '(3 1 4 1 5 9 2 6))

(length  nums)              ; => 8
(first   nums)              ; => 3
(rest    nums)              ; => [1 4 1 5 9 2 6]
(reverse nums)              ; => [6 2 9 5 1 4 1 3]
(sort    nums)              ; => [1 1 2 3 4 5 6 9]
(nth     nums 4)            ; => 5

; Building lists
(cons 0 '(1 2 3))           ; => [0 1 2 3]
(append '(1 2) '(3 4))      ; => [1 2 3 4]
(flatten '(1 (2 3) (4 (5))));  => [1 2 3 4 5]

; Higher-order list processing pipeline
(define (sum-of-squares lst)
  (reduce + (map square lst)))

(sum-of-squares '(1 2 3 4 5))   ; => 55

; zip and process pairs
(zip-lists '(a b c) '(1 2 3))   ; => [[a 1] [b 2] [c 3]]

(define (dot-product u v)
  (reduce + (map (lambda (pair) (* (first pair) (second pair)))
                 (zip-lists u v))))

(dot-product '(1 2 3) '(4 5 6))  ; => 32


; ---------------------------------------------------------------------------
; 8. QUASIQUOTE & CODE AS DATA
; ---------------------------------------------------------------------------

; Quasiquote builds list literals with selective evaluation
(define x 42)
`(the answer is ,x)          ; => [the answer is 42]
`(doubled: ,(* x 2))         ; => [doubled: 84]

; Splicing a list into another
(define extras '(4 5 6))
`(1 2 3 ,@extras 7)          ; => [1 2 3 4 5 6 7]

; Quasiquote is the standard way to write macro bodies
(define template
  (lambda (op a b)
    `(,op ,a ,b)))

(template '+ 1 2)            ; => [+ 1 2]
(evaluate (template '+ 1 2)) ; => 3


; ---------------------------------------------------------------------------
; 9. MACROS — syntax transformers
; ---------------------------------------------------------------------------

; Bootstrap defmacro (normally in your prelude)
(register-macro! defmacro
  (name params body)
  (list 'register-macro! (list 'quote name) params body))

; --- Simple macros ---

; inc/dec
(defmacro inc (n) `(+ ,n 1))
(defmacro dec (n) `(- ,n 1))

(inc 5)    ; => 6
(dec 5)    ; => 4

; unless (inverted if)
(defmacro unless (cond body)
  `(if (not ,cond) ,body None))

(unless false "executed")    ; => executed
(unless true  "skipped")     ; => None

; when  (one-armed if)
(defmacro when (cond body)
  `(if ,cond ,body None))

(when (> 5 3) "yes")         ; => yes

; --- Macro vs Lambda: the key difference ---
;
; A LAMBDA evaluates all arguments before the body runs.
; A MACRO  receives raw (unevaluated) AST and returns new AST.
;
; This means macros can:
;   - Short-circuit evaluation (like 'and', 'or', 'when')
;   - Introduce new binding forms (like 'let', 'letrec')
;   - Generate code based on structure, not just values
;
; Example: 'and' as a macro correctly short-circuits:
(defmacro my-and (a b)
  `(if ,a ,b false))

(my-and false (error! "this is never evaluated"))  ; => false (no error)

; As a function, both args would be evaluated and error! would fire.

; --- swap! macro (mutate two variables) ---
(defmacro swap! (a b)
  (let ((tmp (gensym "tmp")))
    `(let ((,tmp ,a))
       (set! ,a ,b)
       (set! ,b ,tmp))))

(define p 10)
(define q 20)
(swap! p q)
(list p q)    ; => [20 10]

; --- Looping macros ---
(defmacro dotimes (var n body)
  `(let ((,var 0))
     (while (< ,var ,n)
       (begin ,body (set! ,var (inc ,var))))))

(dotimes i 5 (print i))
; prints: 0 1 2 3 4

; --- assert macro ---
(defmacro assert (expr msg)
  `(when (not ,expr)
     (error! (string-append "Assertion failed: " ,msg))))

(assert (= (+ 1 1) 2) "math is broken")  ; passes silently

; --- expand to inspect a macro ---
(expand '(inc 42))           ; => [+ 42 1]
(expand '(when true "yes"))  ; => [if true yes None]


; ---------------------------------------------------------------------------
; 10. MODULES
; ---------------------------------------------------------------------------

(module Math
  (define (square x) (* x x))
  (define (cube   x) (* x x x))
  (define (clamp x lo hi)
    (cond ((< x lo) lo) ((> x hi) hi) (else x)))
  (define pi 3.14159265358979))

Math.pi               ; => 3.14159...
(Math.square 4)       ; => 16

; open brings module bindings into current scope
(open Math)
(square 5)            ; => 25
pi                    ; => 3.14159...


; ---------------------------------------------------------------------------
; 11. READER MACROS — extending the reader
; ---------------------------------------------------------------------------

; Register '~' as shorthand for (inc ...)
(register-reader-macro! '~
  (lambda (stream) (list 'inc (read stream))))

~ 5     ; => 6
~ ~ 5   ; => 7

; Register '#' as shorthand for (length ...)
(register-reader-macro! '#
  (lambda (stream) (list 'length (read stream))))

# '(1 2 3 4 5)    ; => 5


; ---------------------------------------------------------------------------
; 12. SAVE & LOAD — persisting your session
; ---------------------------------------------------------------------------

; Save everything you've defined to the content-addressed store
(save-image "my-session" (find-root))
; => "a3f8c12d4e5b6789-my-session"

; Make it the auto-loaded prelude
(set-prelude! "a3f8c12d4e5b6789-my-session")

; Next time you start the REPL, all your macros, functions, and
; reader macros will be restored automatically.

; Manage paths
(omega-home)         ; => /Users/you/.omega
(store-path)         ; => /Users/you/.omega/store
(config-path)        ; => /Users/you/.omega/config.json
(view-config)        ; => {prelude_file: ..., prelude_enabled: true, ...}

; Move everything to a project-specific location
(set-omega-home! "~/my-project/.omega")


; ---------------------------------------------------------------------------
; 13. CAPABILITY SYSTEM — controlled effects
; ---------------------------------------------------------------------------

(define io-cap (new-capability "io"))
(grant-capability io-cap)

; Only code inside with-capability can use the capability
(with-capability io-cap
  (print "I have io permission"))

; Functions can declare which capabilities they require
(define (safe-log msg)
  (:effects "io")
  (print (string-append "[LOG] " msg)))


; ---------------------------------------------------------------------------
; 14. A COMPLETE PROGRAM — binary search tree
; ---------------------------------------------------------------------------

; BST node: (value left right)  — None means empty
(define (bst-insert tree val)
  (cond
    ((null? tree)    (list val None None))
    ((< val (first tree))
     (list (first tree) (bst-insert (second tree) val) (nth tree 2)))
    ((> val (first tree))
     (list (first tree) (second tree) (bst-insert (nth tree 2) val)))
    (else tree)))   ; duplicate: ignore

(define (bst-contains? tree val)
  (cond
    ((null? tree)   false)
    ((= val (first tree)) true)
    ((< val (first tree)) (bst-contains? (second tree) val))
    (else                 (bst-contains? (nth tree 2)  val))))

(define (bst-inorder tree)
  (if (null? tree) '()
      (append
        (bst-inorder (second tree))
        (list (first tree))
        (bst-inorder (nth tree 2)))))

; Build a BST from a list
(define (list->bst lst)
  (reduce bst-insert lst None))

(define my-tree (list->bst '(5 3 7 1 4 6 8 2)))

(bst-contains? my-tree 4)    ; => true
(bst-contains? my-tree 9)    ; => false
(bst-inorder   my-tree)      ; => [1 2 3 4 5 6 7 8]  (sorted!)
