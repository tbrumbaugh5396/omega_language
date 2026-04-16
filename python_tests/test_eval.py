"""
tests/test_eval.py — Core evaluation, closures, TCO, data model, stdlib
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from unittest.mock import MagicMock
sys.modules.setdefault('prompt_toolkit', MagicMock())
os.environ.setdefault('OMEGA_HOME', tempfile.mkdtemp())

import multiline_repl29 as m

def fresh():
    m.reset_environment()

def ev(s):
    return m.trampoline(m.read_node(m.Stream(m.tokenize(s))), m.env)


# ── Arithmetic ────────────────────────────────────────────────────────────

def test_add():
    fresh(); assert ev('(+ 1 2 3)') == 6

def test_sub():
    fresh(); assert ev('(- 10 3)') == 7

def test_mul():
    fresh(); assert ev('(* 2 3 4)') == 24

def test_div():
    fresh(); assert abs(ev('(/ 10 4)') - 2.5) < 1e-9

def test_mod():
    fresh(); assert ev('(mod 17 5)') == 2

def test_pow():
    fresh(); assert ev('(** 2 10)') == 1024

def test_negation():
    fresh(); assert ev('(- 5)') == -5


# ── Comparison ────────────────────────────────────────────────────────────

def test_lt():
    fresh(); assert ev('(< 1 2)') == True
    assert ev('(< 2 1)') == False

def test_gt():
    fresh(); assert ev('(> 5 3)') == True

def test_eq():
    fresh(); assert ev('(= 42 42)') == True
    assert ev('(= 42 43)') == False


# ── Boolean / truthiness ─────────────────────────────────────────────────

def test_only_false_is_falsy():
    fresh()
    assert ev('(if false 1 2)') == 2
    assert ev('(if 0 1 2)') == 1       # 0 is truthy
    assert ev('(if None 1 2)') == 1    # None is truthy
    assert ev("(if '() 1 2)") == 1    # empty list is truthy
    assert ev('(if true 1 2)') == 1

def test_not():
    fresh()
    assert ev('(not false)') == True
    assert ev('(not true)')  == False
    assert ev('(not 0)')     == False   # 0 is truthy → not is False


# ── Define / set! ────────────────────────────────────────────────────────

def test_define_value():
    fresh(); ev('(define x 42)'); assert ev('x') == 42

def test_define_function():
    fresh()
    ev('(define (square x) (* x x))')
    assert ev('(square 5)') == 25

def test_set_bang_updates():
    fresh(); ev('(define x 1)'); ev('(set! x 99)'); assert ev('x') == 99

def test_set_bang_returns_new_value():
    fresh(); ev('(define a 1)'); assert ev('(set! a 42)') == 42

def test_set_bang_unbound_raises():
    fresh()
    try:
        ev('(set! __ghost__ 1)')
        assert False, "should raise"
    except NameError:
        pass


# ── Closures ─────────────────────────────────────────────────────────────

def test_closure_captures_env_reference():
    """set! mutation is visible through closure reference."""
    fresh()
    ev('(define x 10)')
    ev('(define f (lambda () x))')
    ev('(set! x 20)')
    assert ev('(f)') == 20

def test_closure_no_escape():
    """Inner define doesn't leak into outer scope."""
    fresh()
    ev('(define (make-counter) (define n 0) (lambda () (set! n (+ n 1)) n))')
    ev('(define c (make-counter))')
    assert ev('(c)') == 1
    assert ev('(c)') == 2
    assert ev('(c)') == 3

def test_make_adder():
    fresh()
    ev('(define (make-adder n) (lambda (x) (+ x n)))')
    ev('(define add5 (make-adder 5))')
    assert ev('(add5 10)') == 15
    assert ev('(add5 3)')  == 8


# ── Special forms ────────────────────────────────────────────────────────

def test_if_no_double_eval():
    """Then branch evaluated exactly once."""
    fresh()
    ev('(define c 0)')
    ev('(if true (begin (set! c (+ c 1)) c) 99)')
    assert ev('c') == 1

def test_begin():
    fresh()
    ev('(define x 0)')
    assert ev('(begin (set! x 1) (set! x 2) x)') == 2

def test_let():
    fresh(); assert ev('(let ((x 3) (y 4)) (+ x y))') == 7

def test_let_star():
    fresh(); assert ev('(let* ((x 3) (y (* x 2))) y)') == 6

def test_letrec():
    fresh()
    assert ev('(letrec ((f (lambda (n) (if (= n 0) 1 (* n (f (- n 1))))))) (f 5))') == 120

def test_cond():
    fresh()
    ev('(define (sign x) (cond ((< x 0) (quote neg)) ((= x 0) (quote zero)) (else (quote pos))))')
    assert ev("(sign -1)") == m.Symbol("neg")
    assert ev("(sign 0)")  == m.Symbol("zero")
    assert ev("(sign 1)")  == m.Symbol("pos")

def test_quote():
    fresh()
    r = ev("'(1 2 3)")
    assert r == [1, 2, 3]

def test_quasiquote():
    fresh()
    ev('(define x 5)')
    r = ev('`(+ ,x 1)')
    assert r == [m.Symbol('+'), 5, 1]


# ── First-class functions ─────────────────────────────────────────────────

def test_lambda_as_value():
    fresh()
    assert isinstance(ev('(lambda (x) x)'), m.Lambda)

def test_lambda_passed_as_arg():
    fresh()
    assert ev("(map (lambda (x) (* x x)) '(1 2 3))") == [1, 4, 9]

def test_lambda_returned():
    fresh()
    ev('(define (make-double) (lambda (x) (* 2 x)))')
    ev('(define double (make-double))')
    assert ev('(double 7)') == 14

def test_apply():
    fresh(); assert ev("(apply + '(1 2 3 4 5))") == 15


# ── Tail-call optimization ───────────────────────────────────────────────

def test_tco_no_stack_overflow():
    fresh()
    ev('(define (loop n) (if (= n 0) 0 (loop (- n 1))))')
    assert ev('(loop 100000)') == 0

def test_tco_mutual_recursion():
    fresh()
    ev('(define (my-even? n) (if (= n 0) true  (my-odd?  (- n 1))))')
    ev('(define (my-odd?  n) (if (= n 0) false (my-even? (- n 1))))')
    assert ev('(my-even? 1000)') == True
    assert ev('(my-odd?  1001)') == True


# ── List operations ───────────────────────────────────────────────────────

def test_cons():
    fresh(); assert ev("(cons 1 '(2 3))") == [1, 2, 3]

def test_first_rest():
    fresh()
    assert ev("(first '(1 2 3))") == 1
    assert ev("(rest  '(1 2 3))") == [2, 3]

def test_length():
    fresh(); assert ev("(length '(a b c d))") == 4

def test_append():
    fresh(); assert ev("(append '(1 2) '(3 4))") == [1, 2, 3, 4]

def test_reverse():
    fresh(); assert ev("(reverse '(1 2 3))") == [3, 2, 1]

def test_map():
    fresh(); assert ev("(map (lambda (x) (+ x 1)) '(1 2 3))") == [2, 3, 4]

def test_filter():
    fresh(); assert ev("(filter (lambda (x) (> x 2)) '(1 2 3 4))") == [3, 4]

def test_reduce():
    fresh(); assert ev("(reduce + '(1 2 3 4 5))") == 15

def test_fold():
    fresh(); assert ev("(fold + 0 '(1 2 3 4 5))") == 15

def test_fold_reverse():
    fresh()
    assert ev("(fold (lambda (acc x) (cons x acc)) '() '(1 2 3))") == [3, 2, 1]

def test_sort():
    fresh(); assert ev("(sort '(3 1 4 1 5 9 2 6))") == [1, 1, 2, 3, 4, 5, 6, 9]


# ── Data model / equality ────────────────────────────────────────────────

def test_eq_identity():
    fresh()
    assert ev("(eq? 42 42)") == True
    # Different list objects
    assert ev("(eq? '(1 2 3) '(1 2 3))") == False

def test_equal_structural():
    fresh()
    assert ev("(equal? '(1 2 3) '(1 2 3))") == True
    assert ev("(equal? '(1 2) '(1 3))")     == False
    assert ev("(equal? '(1 (2 3)) '(1 (2 3)))") == True

def test_equal_numbers():
    fresh(); assert ev("(equal? 42 42)") == True

def test_equal_strings():
    fresh(); assert ev('(equal? "hi" "hi")') == True


# ── Strings ───────────────────────────────────────────────────────────────

def test_string_append():
    fresh(); assert ev('(string-append "hello" " " "world")') == "hello world"

def test_string_length():
    fresh(); assert ev('(string-length "omega")') == 5

def test_number_to_string():
    fresh(); assert ev('(number->string 42)') == "42"

def test_string_to_number():
    fresh(); assert ev('(string->number "3.14")') == 3.14


# ── Determinism ───────────────────────────────────────────────────────────

def test_same_output():
    fresh()
    ev('(define (pure x) (* x x))')
    assert ev('(pure 7)') == 49
    assert ev('(pure 7)') == 49

def test_reset_environment():
    fresh()
    ev('(define xyz 999)')
    assert ev('(reset-environment!)') == m.Symbol("ok")
    assert ev('(+ 1 1)') == 2
    try:
        ev('xyz')
        assert False, "should be unbound after reset"
    except NameError:
        pass


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
