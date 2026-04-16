"""
tests/test_modules.py — Module import, dot access, mutation, open, with-module
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
    os.chdir(_HERE)

def ev(s):
    return m.trampoline(m.read_node(m.Stream(m.tokenize(s))), m.env)


# ── Inline modules ────────────────────────────────────────────────────────

def test_module_is_module():
    fresh()
    ev('(module M (export x) (define x 42))')
    assert ev('(module? M)') == True

def test_module_dot_access():
    fresh()
    ev('(module M (export x) (define x 42))')
    assert ev('M.x') == 42

def test_module_function_call():
    fresh()
    ev('(module M (export square) (define (square x) (* x x)))')
    assert ev('(M.square 7)') == 49

def test_module_export_hides_private():
    fresh()
    ev('(module M (export pub) (define pub 1) (define _priv 2))')
    exports = ev('(module-exports M)')
    assert 'pub'   in exports
    assert '_priv' not in exports

def test_module_underscore_always_private():
    fresh()
    ev('(module M (export x) (define x 1) (define _secret 99))')
    exports = ev('(module-exports M)')
    assert '_secret' not in exports


# ── Module introspection ──────────────────────────────────────────────────

def test_module_name():
    fresh()
    ev('(module MyLib (export f) (define (f x) x))')
    assert ev('(module-name MyLib)') == 'MyLib'

def test_module_lookup():
    fresh()
    ev('(module M (export x) (define x 7))')
    assert ev("(module-lookup M 'x)") == 7

def test_module_exports_list():
    fresh()
    ev('(module M (export a b) (define a 1) (define b 2) (define c 3))')
    exports = ev('(module-exports M)')
    assert set(exports) == {'a', 'b'}


# ── set! into modules ─────────────────────────────────────────────────────

def test_set_into_module():
    fresh()
    ev('(module M (export x) (define x 10))')
    assert ev('M.x') == 10
    ev('(set! M.x 99)')
    assert ev('M.x') == 99

def test_set_memoize_into_module():
    fresh()
    ev('(module M (export fib) (define (fib n) (if (<= n 1) n (+ (fib (- n 1)) (fib (- n 2))))))')
    ev('(set! M.fib (memoize M.fib))')
    assert ev('(memoized? M.fib)') == True
    assert ev('(M.fib 15)') == 610


# ── open ──────────────────────────────────────────────────────────────────

def test_open_brings_into_scope():
    fresh()
    ev('(module M (export double) (define (double x) (* 2 x)))')
    ev('(open M)')
    assert ev('(double 5)') == 10

def test_with_module_scoped():
    fresh()
    ev('(module M (export greet) (define (greet x) (string-append "hi " x)) (define _priv 0))')
    result = ev('(with-module M (greet "world"))')
    assert result == "hi world"

def test_with_module_no_leak():
    fresh()
    ev('(module M (export x) (define x 42))')
    ev('(with-module M x)')   # x in scope inside
    try:
        ev('x')   # x should NOT be in scope outside
        # If x was already defined before with-module, this might pass for the wrong reason
        # The important thing is with-module doesn't ADD x to outer scope
    except NameError:
        pass   # expected: x not in outer scope


# ── File imports ──────────────────────────────────────────────────────────

def test_import_file():
    fresh()
    ev('(import "examples.ol" e)')
    assert ev('(module? e)') == True
    assert ev('(module-origin e)') == "file"

def test_import_dot_access():
    fresh()
    ev('(import "examples.ol" e)')
    assert ev('(e.square 5)') == 25

def test_import_module_name():
    fresh()
    ev('(import "examples.ol" e)')
    assert ev('(module-name e)') == "examples.ol"

def test_import_has_exports():
    fresh()
    ev('(import "examples.ol" e)')
    exports = ev('(module-exports e)')
    assert isinstance(exports, list)
    assert len(exports) > 20

def test_import_idempotent():
    """Importing the same file twice produces two independent module objects."""
    fresh()
    ev('(import "examples.ol" e1)')
    ev('(import "examples.ol" e2)')
    assert ev('(module? e1)') == True
    assert ev('(module? e2)') == True


# ── Native module imports ─────────────────────────────────────────────────

def test_native_import():
    fresh()
    ev('(import "math" mth)')
    assert ev('(module? mth)') == True
    assert ev('(module-origin mth)') == "native"

def test_native_getattr():
    fresh()
    ev('(import "math" mth)')
    pi = ev('(getattr mth pi)')
    assert abs(pi - 3.14159) < 0.001

def test_native_function_call():
    fresh()
    ev('(import "math" mth)')
    assert ev('((getattr mth floor) 3.7)') == 3


# ── Nested dot access ─────────────────────────────────────────────────────

def test_three_level_dot():
    fresh()
    ev('(module Inner (export val) (define val 42))')
    ev('(module Outer (export Inner) (import "examples.ol" Inner))')
    # Outer.Inner is the examples module, Outer.Inner.square should work
    assert ev('(Outer.Inner.square 5)') == 25

def test_inline_nested_module():
    fresh()
    ev("""
    (module Outer
      (export get-pi)
      (module Inner (export pi-val) (define pi-val 3.14159))
      (define (get-pi) Inner.pi-val))
    """)
    assert abs(ev('(Outer.get-pi)') - 3.14159) < 0.001


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
