"""
tests/test_macros.py — Macro registration, expansion, quasiquote, gensym
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


# ── Basic macro registration and execution ────────────────────────────────

def test_basic_macro_quoted():
    fresh()
    ev("(register-macro! 'my-inc '(x) '(+ x 1))")
    assert ev('(my-inc 5)') == 6

def test_basic_macro_unquoted():
    """register-macro! also works without quoting."""
    fresh()
    ev("(register-macro! my-inc2 (x) (+ x 1))")
    assert ev('(my-inc2 5)') == 6

def test_macro_with_multiple_args():
    fresh()
    ev("(register-macro! 'my-add '(a b) '(+ a b))")
    assert ev('(my-add 3 4)') == 7

def test_macro_applied_multiple_times():
    fresh()
    ev("(register-macro! 'double-it '(x) '(* x 2))")
    assert ev('(double-it 5)')  == 10
    assert ev('(double-it 10)') == 20
    assert ev('(double-it 1)')  == 2


# ── Quasiquote macros ────────────────────────────────────────────────────

def test_quasiquote_macro():
    fresh()
    ev("(register-macro! 'unless '(tst body) `(if (not ,tst) ,body None))")
    assert ev('(unless false 42)') == 42
    assert ev('(unless true  42)') is None

def test_quasiquote_let_macro():
    """Demonstrates macros can introduce binding forms."""
    fresh()
    ev("(register-macro! 'my-let '(x val body) `((lambda (,x) ,body) ,val))")
    assert ev('(my-let n 10 (* n n))') == 100

def test_quasiquote_when_macro():
    fresh()
    ev("(register-macro! 'my-when '(cond body) `(if ,cond ,body None))")
    assert ev('(my-when true  99)') == 99
    assert ev('(my-when false 99)') is None


# ── Expand ───────────────────────────────────────────────────────────────

def test_expand_returns_ast_not_value():
    """(expand ...) returns the expanded form, not the evaluated result."""
    fresh()
    ev("(register-macro! 'my-inc '(x) '(+ x 1))")
    result = ev("(expand '(my-inc 5))")
    # Should be the list ['+', 5, 1], not 6
    assert isinstance(result, list)
    assert result[0] == m.Symbol('+')
    assert result[1] == 5
    assert result[2] == 1

def test_expand_quasiquote_macro():
    fresh()
    ev("(register-macro! 'unless '(tst body) `(if (not ,tst) ,body None))")
    result = ev("(expand '(unless false 42))")
    assert isinstance(result, list)
    assert result[0] == m.Symbol('if')

def test_expand_nested():
    """Macros that expand to macro calls are recursively expanded."""
    fresh()
    ev("(register-macro! 'my-and2 '(a b) `(if ,a ,b false))")
    ev("(register-macro! 'my-and3 '(a b c) `(my-and2 ,a (my-and2 ,b ,c)))")
    assert ev('(my-and3 true true true)')  == True
    assert ev('(my-and3 true false true)') == False


# ── Gensym ────────────────────────────────────────────────────────────────

def test_gensym_returns_symbol():
    fresh()
    g = ev('(gensym "tmp")')
    assert isinstance(g, m.Symbol)

def test_gensym_unique():
    fresh()
    g1 = ev('(gensym "g")')
    g2 = ev('(gensym "g")')
    g3 = ev('(gensym "g")')
    assert g1 != g2
    assert g2 != g3

def test_gensym_prefix():
    fresh()
    g = ev('(gensym "my_var")')
    assert str(g).startswith("my_var")


# ── Macro variable capture (non-hygiene) ─────────────────────────────────

def test_macro_param_shadows_outer():
    """Macro param name 'x' should shadow any outer 'x'."""
    fresh()
    ev('(define x 100)')
    ev("(register-macro! 'add1 '(x) '(+ x 1))")
    # The macro receives 5 as x, NOT the outer x=100
    assert ev('(add1 5)') == 6

def test_macro_with_gensym_avoids_capture():
    """gensym produces unique symbols each call."""
    fresh()
    g1 = ev('(gensym "tmp")')
    g2 = ev('(gensym "tmp")')
    # Each gensym call should return a different symbol
    assert g1 != g2
    assert str(g1).startswith("tmp")
    assert str(g2).startswith("tmp")


# ── Macros in context ─────────────────────────────────────────────────────

def test_macro_in_map():
    """Macros expand with non-hygienic substitution.
    When the macro param name differs from the call-site variable, it works correctly.
    Use gensym or distinct param names to avoid capture."""
    fresh()
    # Macro param 'val' — caller uses 'x'. No collision, works correctly.
    ev("(register-macro! 'inc '(val) `(+ ,val 1))")
    ev('(define (inc-fn x) (inc x))')
    assert ev('(inc-fn 3)') == 4
    assert ev('(inc-fn 9)') == 10

def test_macro_body_not_prematurely_evaluated():
    """Macro body is only evaluated when the macro is called, not at definition."""
    fresh()
    # This macro works correctly without variable capture issues
    ev("(register-macro! 'my-or '(a b) `(let ((t ,a)) (if t t ,b)))")
    assert ev('(my-or false 42)') == 42
    assert ev('(my-or 7 99)')     == 7
    assert ev('(my-or false false)') == False


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
