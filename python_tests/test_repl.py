"""
tests/test_repl.py — REPL balance, error messages, debug mode, verify.ol
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from unittest.mock import MagicMock
sys.modules.setdefault('prompt_toolkit', MagicMock())
os.environ.setdefault('OMEGA_HOME', tempfile.mkdtemp())

import multiline_repl29 as m

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def fresh():
    m.reset_environment()
    m.READ_TABLE.pop("~", None)
    m.READ_TABLE.pop("#", None)
    os.chdir(_HERE)

def ev(s):
    return m.trampoline(m.read_node(m.Stream(m.tokenize(s))), m.env)


# ── Balance (multiline input detection) ──────────────────────────────────

def test_balance_complete():
    assert m.balance("(+ 1 2)") == 0

def test_balance_open():
    assert m.balance("(+ 1 2") == 1

def test_balance_nested():
    assert m.balance("(+ (1 2)") == 1

def test_balance_double_nested():
    assert m.balance("(+ (1 (2 3)") == 2

def test_balance_closed():
    assert m.balance("(+ 1 2))") == -1

def test_balance_empty():
    assert m.balance("") == 0

def test_balance_comment_only():
    assert m.balance("; this is a comment") == 0

def test_balance_multiline():
    text = "(define (f x)\n  (+ x 1)"
    assert m.balance(text) == 1


# ── Error messages ────────────────────────────────────────────────────────

def test_name_error_message():
    fresh()
    try:
        ev('__definitely_unbound__')
        assert False, "should raise"
    except NameError as e:
        assert "Unbound symbol" in str(e)

def test_type_error_calling_non_function():
    fresh()
    ev('(define x 42)')
    try:
        ev('(x 1)')
        assert False, "should raise"
    except TypeError as e:
        assert "42" in str(e) or "function" in str(e).lower()

def test_clean_errors_by_default():
    """_DEBUG_MODE[0] should be False by default."""
    fresh()
    assert m._DEBUG_MODE[0] == False

def test_debug_mode_toggle():
    fresh()
    assert ev('(debug-mode)') == False
    ev('(debug-mode true)');  assert ev('(debug-mode)') == True
    ev('(debug-mode false)'); assert ev('(debug-mode)') == False

def test_debug_mode_returns_ok():
    fresh()
    assert ev('(debug-mode true)')  == m.Symbol("ok")
    assert ev('(debug-mode false)') == m.Symbol("ok")


# ── Multiline evaluation ──────────────────────────────────────────────────

def test_multiline_expr():
    fresh()
    assert ev('(+\n  1\n  2)') == 3

def test_multiline_define():
    fresh()
    ev('(define (f x)\n  (* x x))')
    assert ev('(f 5)') == 25

def test_multiple_exprs_single_string():
    fresh()
    # Tokenize and read multiple forms
    source = "(define x 10) (define y 20) (+ x y)"
    stream = m.Stream(m.tokenize(source))
    results = []
    while stream.peek() is not None:
        node = m.read_node(stream)
        if node:
            results.append(m.trampoline(node, m.env))
    assert results[-1] == 30


# ── Reset environment ────────────────────────────────────────────────────

def test_reset_returns_ok():
    fresh()
    assert ev('(reset-environment!)') == m.Symbol("ok")

def test_reset_clears_user_defs():
    fresh()
    ev('(define my_unique_xyz 999)')
    ev('(reset-environment!)')
    try:
        ev('my_unique_xyz')
        assert False
    except NameError:
        pass

def test_reset_preserves_primitives():
    """After reset, arithmetic and core primitives still work."""
    fresh()
    ev('(define x 5)')
    ev('(reset-environment!)')
    assert ev('(+ 1 2)') == 3
    assert ev("(map (lambda (x) x) '(1 2))") == [1, 2]


# ── Reader macros ────────────────────────────────────────────────────────

def test_register_reader_macro():
    fresh()
    ev('(define (inc x) (+ x 1))')
    ev("(register-reader-macro! '~ (lambda (stream) (list 'inc (read stream))))")
    assert ev('~ 5') == 6

def test_reader_macro_chained():
    fresh()
    ev('(define (inc x) (+ x 1))')
    ev("(register-reader-macro! '~ (lambda (stream) (list 'inc (read stream))))")
    assert ev('~ ~ 5') == 7

def test_reader_macro_with_load_isolation():
    """Reader macros from previous sessions don't corrupt re-loads."""
    fresh()
    ev("(register-reader-macro! '~ (lambda (stream) (list 'inc (read stream))))")
    # Loading verify.ol should not be corrupted by the ~ reader macro
    ev('(load "verify.ol")')
    # If isolation works, the load completes without error


# ── Python interop ───────────────────────────────────────────────────────

def test_py_eval():
    fresh(); assert ev('(py-eval "1 + 1")') == 2

def test_py_eval_error_caught():
    fresh()
    try:
        ev('(py-eval "1/0")')
        assert False
    except Exception as e:
        assert "zero" in str(e).lower() or "ZeroDivision" in str(e)

def test_native_import():
    fresh()
    result = ev('(import "math" mth)')
    assert isinstance(result, m.Module)
    assert ev('(module-origin mth)') == "native"


# ── verify.ol end-to-end ─────────────────────────────────────────────────

def test_verify_ol_loads_clean():
    """verify.ol should load with 0 errors."""
    fresh()
    content = open(os.path.join(_HERE, "verify.ol")).read()
    stream  = m.Stream(m.tokenize(content))
    errors  = []
    n       = 0
    while stream.peek() is not None:
        node = m.read_node(stream)
        if node is None: continue
        try:
            m.trampoline(node, m.env); n += 1
        except Exception as e:
            errors.append((n, str(e)[:80]))
            n += 1
    assert errors == [], f"verify.ol errors: {errors}"
    assert n > 50, f"Expected 50+ forms, got {n}"


# ── Interop / Python errors ───────────────────────────────────────────────

def test_py_eval_list():
    fresh()
    result = ev('(py-eval "list(range(5))")')
    assert result == [0, 1, 2, 3, 4]

def test_py_exec_side_effect():
    fresh()
    ev('(py-exec "import os as _os_test; _test_val = 42")')
    result = ev('(py-eval "_test_val")')
    assert result == 42


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
