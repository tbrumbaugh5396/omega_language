"""
tests/test_memo.py — Memoization: memoize, memoize!, memoize-rec!, cache keys
"""
import sys, os, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from unittest.mock import MagicMock
sys.modules.setdefault('prompt_toolkit', MagicMock())
os.environ.setdefault('OMEGA_HOME', tempfile.mkdtemp())

import multiline_repl29 as m

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def fresh():
    m.reset_environment()
    os.chdir(_HERE)

def ev(s):
    return m.trampoline(m.read_node(m.Stream(m.tokenize(s))), m.env)


# ── memoize (non-mutating) ────────────────────────────────────────────────

def test_memoize_basic():
    fresh()
    ev('(define (add a b) (+ a b))')
    ev('(define madd (memoize add))')
    assert ev('(madd 3 4)') == 7

def test_memoize_caches_result():
    fresh()
    call_count = [0]
    # Use a counter via py-eval to track calls
    ev('(define calls 0)')
    ev('(define (counting-add a b) (set! calls (+ calls 1)) (+ a b))')
    ev('(define mcadd (memoize counting-add))')
    ev('(mcadd 3 4)')
    ev('(mcadd 3 4)')   # second call — should hit cache
    ev('(mcadd 3 4)')   # third call — should hit cache
    assert ev('calls') == 1   # only computed once

def test_memoize_different_args():
    fresh()
    ev('(define calls 0)')
    ev('(define (f x) (set! calls (+ calls 1)) (* x x))')
    ev('(define mf (memoize f))')
    ev('(mf 3)'); ev('(mf 4)'); ev('(mf 3)')  # 3 twice
    assert ev('calls') == 2   # 3 and 4 each computed once

def test_memoized_predicate():
    fresh()
    ev('(define (sq x) (* x x))')
    ev('(define msq (memoize sq))')
    assert ev('(memoized? msq)') == True
    assert ev('(memoized? sq)')  == False

def test_memoize_does_not_mutate_original():
    """memoize returns a new function; original is unchanged."""
    fresh()
    ev('(define (sq x) (* x x))')
    ev('(define msq (memoize sq))')
    assert ev('(memoized? sq)') == False
    assert ev('(memoized? msq)') == True


# ── memo-clear! ───────────────────────────────────────────────────────────

def test_memo_clear():
    fresh()
    ev('(define calls 0)')
    ev('(define (f x) (set! calls (+ calls 1)) (* x x))')
    ev('(define mf (memoize f))')
    ev('(mf 5)')        # fills cache
    assert ev('calls') == 1
    ev('(memo-clear! mf)')
    ev('(mf 5)')        # should recompute
    assert ev('calls') == 2

def test_memo_clear_idempotent():
    fresh()
    ev('(define mf (memoize (lambda (x) x)))')
    ev('(mf 1)')
    ev('(memo-clear! mf)')
    ev('(memo-clear! mf)')  # double clear should not error
    assert ev('(mf 1)') == 1


# ── memoize! (in-place) ───────────────────────────────────────────────────

def test_memoize_bang_quoted():
    fresh()
    ev('(define (fib n) (if (<= n 1) n (+ (fib (- n 1)) (fib (- n 2)))))')
    ev("(memoize! 'fib)")
    assert ev('(fib 20)') == 6765

def test_memoize_bang_unquoted():
    fresh()
    ev('(define (fib n) (if (<= n 1) n (+ (fib (- n 1)) (fib (- n 2)))))')
    ev('(memoize! fib)')   # no quote
    assert ev('(fib 20)') == 6765

def test_memoize_bang_makes_fib32_fast():
    """After memoize!, fib(32) should be instant once fib(30) is cached."""
    fresh()
    ev('(define (fib n) (if (<= n 1) n (+ (fib (- n 1)) (fib (- n 2)))))')
    ev('(memoize! fib)')
    ev('(fib 30)')          # warm up cache
    t = time.time()
    result = ev('(fib 32)')
    elapsed = time.time() - t
    assert result == 2178309
    assert elapsed < 0.05   # instant from cache

def test_memoize_bang_idempotent():
    """Calling memoize! twice is safe."""
    fresh()
    ev('(define (f x) (* x x))')
    ev("(memoize! 'f)")
    ev("(memoize! 'f)")   # second time should not break
    assert ev('(f 5)') == 25

def test_memoize_bang_marks_memoized():
    fresh()
    ev('(define (f x) x)')
    ev('(memoize! f)')
    assert ev('(memoized? f)') == True

def test_memoize_bang_alias():
    """memoize! on an alias also rebinds the original function."""
    fresh()
    ev('(define (fib n) (if (<= n 1) n (+ (fib (- n 1)) (fib (- n 2)))))')
    ev('(define fibcopy fib)')
    ev('(memoize! fibcopy)')
    assert ev('(fibcopy 20)') == 6765
    t = time.time(); ev('(fibcopy 30)'); ev('(fibcopy 32)'); e = time.time() - t
    assert e < 0.5   # both fast

def test_memoize_bang_after_module_import():
    """The session scenario: define name = module.fn, then memoize! name."""
    fresh()
    ev('(import "examples.ol" e)')
    # examples.ol has a fib — import it locally
    ev('(define fib e.fib)')
    ev('(memoize! fib)')
    assert ev('(memoized? fib)') == True
    assert ev('(fib 20)') == 6765
    t = time.time(); ev('(fib 30)'); ev('(fib 32)'); e = time.time() - t
    assert e < 0.5


# ── memoize-rec! (mutual recursion) ──────────────────────────────────────

def test_memoize_rec_basic():
    fresh()
    ev('(define (my-even? n) (if (= n 0) true  (my-odd?  (- n 1))))')
    ev('(define (my-odd?  n) (if (= n 0) false (my-even? (- n 1))))')
    ev("(memoize-rec! '(my-even? my-odd?))")
    assert ev('(my-even? 10)') == True
    assert ev('(my-odd?  11)') == True

def test_memoize_rec_both_memoized():
    fresh()
    ev('(define (e? n) (if (= n 0) true  (o? (- n 1))))')
    ev('(define (o? n) (if (= n 0) false (e? (- n 1))))')
    ev("(memoize-rec! '(e? o?))")
    assert ev('(memoized? e?)') == True
    assert ev('(memoized? o?)') == True

def test_memoize_rec_fast():
    fresh()
    ev('(define (e? n) (if (= n 0) true  (o? (- n 1))))')
    ev('(define (o? n) (if (= n 0) false (e? (- n 1))))')
    ev("(memoize-rec! '(e? o?))")
    t = time.time()
    assert ev('(e? 40)') == True
    elapsed = time.time() - t
    assert elapsed < 1.0   # should be fast after memoization

def test_memoize_rec_correctness():
    fresh()
    ev('(define (e? n) (if (= n 0) true  (o? (- n 1))))')
    ev('(define (o? n) (if (= n 0) false (e? (- n 1))))')
    ev("(memoize-rec! '(e? o?))")
    for i in range(10):
        expected_even = (i % 2 == 0)
        assert ev(f'(e? {i})') == expected_even
        assert ev(f'(o? {i})') == (not expected_even)


# ── Structural cache keys ─────────────────────────────────────────────────

def test_structural_key_equal_lists():
    """Two structurally equal lists map to the same cache entry."""
    fresh()
    ev('(define (lsum lst) (if (null? lst) 0 (+ (first lst) (lsum (rest lst)))))')
    ev('(define ms (memoize lsum))')
    ev("(ms '(1 2 3))")
    ms_fn = m.env.find("ms")["ms"]
    size_after_first = len(ms_fn._memo)
    ev("(ms '(1 2 3))")   # same structure — should be a cache hit, no new entry
    ev("(ms '(1 2 3))")
    assert len(ms_fn._memo) == size_after_first   # no growth

def test_structural_key_different_lists():
    """Different lists produce different cache entries."""
    fresh()
    ev('(define (lsum lst) (if (null? lst) 0 (+ (first lst) (lsum (rest lst)))))')
    ev('(define ms (memoize lsum))')
    ev("(ms '(1 2 3))")
    ms_fn = m.env.find("ms")["ms"]
    before = len(ms_fn._memo)
    ev("(ms '(4 5 6))")   # different list — new entry
    assert len(ms_fn._memo) > before

def test_structural_key_nested_lists():
    fresh()
    ev('(define calls 0)')
    ev('(define (f x) (set! calls (+ calls 1)) x)')
    ev('(define mf (memoize f))')
    ev("(mf '(1 (2 3)))")
    ev("(mf '(1 (2 3)))")   # same nested structure
    assert ev('calls') == 1


# ── trace-calls ───────────────────────────────────────────────────────────

def test_trace_calls_returns_correct_result():
    fresh()
    ev('(define (add a b) (+ a b))')
    ev('(define tadd (trace-calls add))')
    assert ev('(tadd 3 4)') == 7

def test_traced_predicate():
    fresh()
    ev('(define (f x) x)')
    ev('(define tf (trace-calls f))')
    assert ev('(traced? tf)') == True
    assert ev('(traced? f)')  == False

def test_untrace_calls():
    fresh()
    ev('(define (f x) x)')
    ev('(define tf (trace-calls f))')
    ev('(define uf (untrace-calls tf))')
    assert ev('(traced? uf)') == False
    assert ev('(uf 42)') == 42


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
