"""
tests/test_transpiler.py — Lisp→Python (transpiler12.ol) and Python→Lisp (python_to_lisp4.py)
"""
import sys, os, tempfile, textwrap, subprocess
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

def load_transpiler():
    fresh()
    ev('(load "transpiler12.ol")')


# ── transpile (core expr → Python string) ────────────────────────────────

def test_transpile_number():
    load_transpiler()
    assert ev('(transpile 42)') == "42"

def test_transpile_true_false():
    load_transpiler()
    assert ev('(transpile true)')  == "True"
    assert ev('(transpile false)') == "False"

def test_transpile_symbol():
    load_transpiler()
    assert ev("(transpile 'square)") == "square"

def test_transpile_name_mangling():
    load_transpiler()
    assert ev("(transpile 'my-fn)")   == "my_fn"
    assert ev("(transpile 'null_p)")  == "null_p"

def test_transpile_arithmetic():
    load_transpiler()
    r = ev("(transpile '(+ 1 2))")
    assert "1" in r and "2" in r and "+" in r

def test_transpile_eq():
    load_transpiler()
    r = ev("(transpile '(eq? a b))")
    assert " is " in r

def test_transpile_equal():
    load_transpiler()
    r = ev("(transpile '(equal? a b))")
    assert "_structural_equal" in r

def test_transpile_fold():
    load_transpiler()
    r = ev("(transpile '(fold f 0 lst))")
    assert "lisp_fold" in r

def test_transpile_memoize():
    load_transpiler()
    r = ev("(transpile '(memoize f))")
    assert "_make_memoized_wrapper" in r

def test_transpile_memoized_p():
    load_transpiler()
    r = ev("(transpile '(memoized? f))")
    assert "_is_memoized" in r

def test_transpile_trace_calls():
    load_transpiler()
    r = ev("(transpile '(trace-calls f))")
    assert "_make_traced_wrapper" in r

def test_transpile_module_p():
    load_transpiler()
    r = ev("(transpile '(module? x))")
    assert "isinstance" in r and "Module" in r

def test_transpile_module_name():
    load_transpiler()
    r = ev("(transpile '(module-name m))")
    assert "name" in r

def test_transpile_if():
    load_transpiler()
    r = ev("(transpile '(if (> x 0) x 0))")
    assert " if " in r and " else " in r

def test_transpile_lambda():
    load_transpiler()
    r = ev("(transpile '(lambda (x y) (+ x y)))")
    assert "lambda" in r and "x" in r and "y" in r

def test_transpile_let():
    load_transpiler()
    r = ev("(transpile '(let ((x 1) (y 2)) (+ x y)))")
    assert "lambda" in r   # let → (lambda ...)()

def test_transpile_not():
    load_transpiler()
    r = ev("(transpile '(not x))")
    assert "not" in r

def test_transpile_null_p():
    load_transpiler()
    r = ev("(transpile '(null? x))")
    assert "None" in r or "[]" in r


# ── transpile-module and runtime prelude ──────────────────────────────────

def test_transpile_module_includes_prelude():
    load_transpiler()
    ev('(define (sq x) (* x x))')
    result = ev("(transpile-module '(sq))")
    assert "Omega Runtime Prelude" in result
    assert "def sq" in result

def test_transpile_module_includes_v1_helpers():
    load_transpiler()
    ev('(define (sq x) (* x x))')
    result = ev("(transpile-module '(sq))")
    assert "_structural_equal" in result
    assert "lisp_fold" in result
    assert "_make_memoized_wrapper" in result
    assert "_make_traced_wrapper" in result

def test_transpile_file_creates_file():
    load_transpiler()
    ev('(define (sq x) (* x x))')
    out = os.path.join(tempfile.mkdtemp(), "sq.py")
    ev(f'(transpile-file "{out}" (quote (sq)))')
    assert os.path.exists(out)
    content = open(out).read()
    assert "def sq" in content

def test_transpiled_file_is_importable():
    """The output .py file should be importable and callable from Python."""
    load_transpiler()
    ev('(define (square x) (* x x))')
    ev('(define (cube x)   (* x x x))')
    tmpdir = tempfile.mkdtemp()
    out = os.path.join(tmpdir, "geom.py")
    ev(f'(transpile-file "{out}" (quote (square cube)))')

    result = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, '{tmpdir}'); import geom; print(geom.square(5)); print(geom.cube(3))"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().split('\n')
    assert lines[0] == "25"
    assert lines[1] == "27"

def test_transpile_single_symbol():
    load_transpiler()
    ev('(define (inc x) (+ x 1))')
    result = ev("(transpile-module 'inc)")   # single symbol, not list
    assert "def inc" in result


# ── Python → Lisp transpiler ──────────────────────────────────────────────

def _py2lisp(source: str, show_meta=False) -> str:
    sys.path.insert(0, _HERE)
    from python_to_lisp4 import transpile_source
    return transpile_source(source, show_meta=show_meta)

def test_py2lisp_simple_function():
    result = _py2lisp("def square(x):\n    return x * x\n")
    assert "define" in result
    assert "square" in result

def test_py2lisp_if_statement():
    result = _py2lisp("def sign(x):\n    if x > 0:\n        return 1\n    else:\n        return -1\n")
    assert "if" in result
    assert ">" in result

def test_py2lisp_assignment():
    result = _py2lisp("x = 42\n")
    assert "define" in result
    assert "42" in result

def test_py2lisp_import():
    result = _py2lisp("import math\n")
    assert "import" in result
    assert "math" in result

def test_py2lisp_lambda():
    result = _py2lisp("f = lambda x: x + 1\n")
    assert "lambda" in result

def test_py2lisp_list_comprehension():
    result = _py2lisp("xs = [x * x for x in items]\n")
    assert "map" in result or "define" in result   # converted to map or loop

def test_py2lisp_augmented_assign():
    result = _py2lisp("x += 1\n")
    assert "set!" in result or "define" in result

def test_py2lisp_strips_omega_prelude():
    """Files that are already Omega output have their prelude stripped."""
    prelude_and_fn = textwrap.dedent("""\
        # ── Omega Runtime Prelude ────────────────────────────────────────────────
        # Generated by transpiler12.ol. Do not edit manually.
        class Symbol(str):
            pass
        class StringLiteral(str):
            pass
        def null_p(x): return x is None or x == []
        # ── Transpiled functions ─────────────────────────────────────────────────

        def square(x):
            return (x * x)
    """)
    result = _py2lisp(prelude_and_fn)
    # Should not re-lift the prelude classes as code
    assert "class Symbol" not in result or result.count("Symbol") <= 2

def test_py2lisp_confidence_annotations():
    """show_meta=True produces output; both show_meta modes produce valid Lisp."""
    result_meta  = _py2lisp("def f(x):\n    return x\n", show_meta=True)
    result_clean = _py2lisp("def f(x):\n    return x\n", show_meta=False)
    # Both modes should produce output containing the function
    assert "define" in result_meta
    assert "define" in result_clean

def test_py2lisp_no_meta_clean():
    result = _py2lisp("def f(x):\n    return x\n", show_meta=False)
    assert "[1.0]" not in result
    assert "[0." not in result


# ── Round-trip smoke test ─────────────────────────────────────────────────

def test_roundtrip_simple_function():
    """A simple pure function should round-trip to equivalent Python."""
    load_transpiler()

    # Start: Python source
    py_src = textwrap.dedent("""\
        def double(x):
            return x * 2
    """)

    tmpdir = tempfile.mkdtemp()
    src_py  = os.path.join(tmpdir, "orig.py")
    rt_ol   = os.path.join(tmpdir, "rt.ol")
    rt_py   = os.path.join(tmpdir, "rt.py")

    with open(src_py, 'w') as f:
        f.write(py_src)

    # Step 1: Python → Lisp
    from python_to_lisp4 import transpile_file as py2lisp_file
    lisp_src = py2lisp_file(src_py, show_meta=False)
    with open(rt_ol, 'w') as f:
        f.write(lisp_src)

    # Step 2: Load Lisp definitions into Omega
    ev(f'(load "{rt_ol}")')

    # Step 3: Lisp → Python
    ev(f'(transpile-file "{rt_py}" (quote (double)))')

    assert os.path.exists(rt_py)
    content = open(rt_py).read()
    assert "double" in content

    # Step 4: Run the round-tripped Python
    result = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, '{tmpdir}'); import rt; print(rt.double(5))"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10"


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
