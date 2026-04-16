"""
python_to_lisp.py — Python → Omega Lisp AST transpiler

Converts Python source code into the Lisp AST format used by the Omega
interpreter (Symbol / list / literal values), with lossiness annotations.

Architecture
------------
Python source
  → Python AST (stdlib `ast` module)
  → Omega Lisp AST (Symbol + list + literals + meta annotations)
  → Pretty-printed S-expressions

Usage
-----
  from python_to_lisp import py_to_lisp, pretty_print, transpile_file

  # Get annotated Lisp AST
  ast_node = py_to_lisp("def square(x):\n    return x * x")

  # Pretty-print as S-expressions
  print(pretty_print(ast_node))

  # Write to file
  transpile_file("square.py", "square.ol")

From the Omega REPL (after (load "py_lift.ol")):
  (py->lisp "square.py")    ; load and print
  (py-ast "square.py")      ; return raw AST list
"""

import ast
import json
from dataclasses import dataclass, field
from typing import Any, Union

# ── AST node types (mirror Omega's Symbol/StringLiteral) ─────────────────

class Symbol(str):
    """A Lisp symbol / identifier."""
    pass

class Meta(dict):
    """Annotation dict attached to AST nodes via node[0] == '__meta__'."""
    pass


# ── Annotation helpers ────────────────────────────────────────────────────

def _meta(confidence=1.0, lossy=False, reason=None, python_type=None,
          lineno=None, col=None, macro_origin=None, warnings=None):
    """Build a metadata annotation dict."""
    m = {"confidence": confidence, "lossy": lossy, "source": "python"}
    if reason:        m["reason"]       = reason
    if python_type:   m["python_type"]  = python_type
    if lineno:        m["lineno"]       = lineno
    if col:           m["col"]          = col
    if macro_origin:  m["macro_origin"] = macro_origin
    if warnings:      m["warnings"]     = warnings
    return m

def _annotate(node, **kwargs):
    """
    Wrap a Lisp AST node with metadata.
    Returns a list:  ['__meta__', {meta-dict}, node]
    When emitting, pretty_print strips the wrapper and uses the metadata
    as a comment or attribute.
    """
    if not kwargs:
        return node
    return ["__meta__", _meta(**kwargs), node]

def _loc(py_node):
    """Extract line/col from a Python AST node."""
    lineno = getattr(py_node, 'lineno', None)
    col    = getattr(py_node, 'col_offset', None)
    return {"lineno": lineno, "col": col}


# ── Main converter ────────────────────────────────────────────────────────

def py_to_lisp(source: str) -> list:
    """
    Parse Python source and return a Lisp AST as a Python list/Symbol tree.

    The top-level result is always:
      ['begin', form1, form2, ...]
    with a __meta__ annotation wrapping the whole module.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return _annotate(
            [Symbol("python-parse-error"), str(e)],
            lossy=True, confidence=0.0, reason=str(e)
        )
    forms  = [_convert(node) for node in tree.body]
    result = [Symbol("begin")] + forms
    return _annotate(result, python_type="Module",
                     confidence=_module_confidence(forms))


def _module_confidence(forms):
    """Estimate overall confidence from individual form annotations."""
    if not forms: return 1.0
    confs = []
    for f in forms:
        if isinstance(f, list) and len(f) == 3 and f[0] == "__meta__":
            confs.append(f[1].get("confidence", 1.0))
        else:
            confs.append(1.0)
    return round(sum(confs) / len(confs), 2)


def _convert(node):
    """Dispatch on Python AST node type → Lisp form."""
    name = type(node).__name__
    handler = _HANDLERS.get(name)
    if handler:
        return handler(node)
    # Unknown node — emit opaque placeholder with warning
    return _annotate(
        [Symbol("python-opaque"), Symbol(name)],
        lossy=True, confidence=0.0, python_type=name,
        warnings=[f"Unsupported Python construct: {name}"]
    )


# ── Statement handlers ────────────────────────────────────────────────────

def _convert_module(node):
    forms = [_convert(n) for n in node.body]
    return _annotate([Symbol("begin")] + forms, python_type="Module")

def _convert_expr_stmt(node):
    # Expression used as statement (e.g. a string docstring or bare call)
    return _convert(node.value)

# ── Assignment target helper ───────────────────────────────────────────────
#
# Python assignment targets can be:
#   ast.Name       →  simple identifier   x
#   ast.Attribute  →  attribute ref       self.x    obj.field
#   ast.Subscript  →  index ref           a[i]      d["key"]
#   ast.Starred    →  starred             *rest
#   ast.Tuple      →  tuple unpack        a, b = ...
#   ast.List       →  list unpack         [a, b] = ...
#
# We convert each to an appropriate Lisp form so callers never crash on
# an unexpected node type.

def _convert_target(node):
    """Convert any Python assignment target to a Lisp lvalue form."""
    if isinstance(node, ast.Name):
        return Symbol(node.id)
    if isinstance(node, ast.Attribute):
        # self.x  →  (getattr self x)
        return _annotate(
            [Symbol("getattr"), _convert(node.value), Symbol(node.attr)],
            python_type="Attribute", confidence=0.85,
            reason="attribute assignment target"
        )
    if isinstance(node, ast.Subscript):
        # a[i]  →  (get a i)
        return _annotate(
            [Symbol("get"), _convert(node.value), _convert(node.slice)],
            python_type="Subscript"
        )
    if isinstance(node, ast.Starred):
        return _annotate(
            [Symbol("*spread"), _convert_target(node.value)],
            python_type="Starred", lossy=True, confidence=0.6
        )
    if isinstance(node, (ast.Tuple, ast.List)):
        elts = [_convert_target(e) for e in node.elts]
        return _annotate(
            [Symbol("tuple")] + elts,
            python_type="TupleTarget", lossy=True, confidence=0.7,
            reason="destructuring target"
        )
    # Fallback: convert as a normal expression
    return _convert(node)

def _convert_assign(node):
    # Simple assignment: x = expr  →  (define x expr)
    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return _annotate(
            [Symbol("define"),
             Symbol(node.targets[0].id),
             _convert(node.value)],
            python_type="Assign", **_loc(node)
        )
    elif len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
        # Tuple/list unpacking: a, b = expr  →  (define-values (a b) expr)
        names = [_convert_target(e) for e in node.targets[0].elts]
        return _annotate(
            [Symbol("define-values"), names, _convert(node.value)],
            python_type="Assign", lossy=True, confidence=0.7,
            reason="tuple unpacking approximated as define-values",
            **_loc(node)
        )
    elif len(node.targets) == 1:
        # Attribute or subscript target: self.x = v  →  (set! (getattr self x) v)
        target = _convert_target(node.targets[0])
        return _annotate(
            [Symbol("set!"), target, _convert(node.value)],
            python_type="Assign", lossy=True, confidence=0.7,
            reason="non-name assignment target", **_loc(node)
        )

def _convert_aug_assign(node):
    # x += y      →  (set! x (+ x y))
    # self.x += y →  (set! (getattr self x) (+ (getattr self x) y))
    op_sym = _binop_sym(node.op)
    target = _convert_target(node.target)
    return _annotate(
        [Symbol("set!"), target,
         [op_sym, target, _convert(node.value)]],
        python_type="AugAssign", **_loc(node)
    )

def _convert_ann_assign(node):
    # x: int = 5       →  (define x 5)
    # self.x: int = 5  →  (set! (getattr self x) 5)
    # Either way the annotation is dropped (noted in meta).
    val    = _convert(node.value) if node.value else Symbol("None")
    ann    = ast.unparse(node.annotation) if hasattr(ast, 'unparse') else "?"
    target = _convert_target(node.target)
    # Use define only for simple name targets; set! for everything else
    if isinstance(node.target, ast.Name):
        form = [Symbol("define"), target, val]
    else:
        form = [Symbol("set!"), target, val]
    return _annotate(
        form,
        python_type="AnnAssign", confidence=0.9,
        reason=f"type annotation '{ann}' dropped", **_loc(node)
    )

def _convert_return(node):
    # return expr  →  expr  (return is implicit in Lisp function bodies)
    if node.value is None:
        return Symbol("None")
    return _convert(node.value)

def _convert_function_def(node, is_async=False):
    name    = Symbol(node.name)
    params  = _convert_arguments(node.args)
    body    = _convert_body(node.body)
    meta_kw = dict(python_type="AsyncFunctionDef" if is_async else "FunctionDef",
                   **_loc(node))
    result  = [Symbol("define"), [name] + params, body]
    if node.decorator_list:
        result = _annotate(result, lossy=True, confidence=0.5,
                           reason="decorators not supported in Lisp IR",
                           **meta_kw)
        for dec in reversed(node.decorator_list):
            result = [_convert(dec), result]
        return _annotate(result, lossy=True, confidence=0.5,
                         reason="decorators wrapped as calls", **meta_kw)
    if is_async:
        return _annotate(result, lossy=True, confidence=0.6,
                         reason="async/await semantics not preserved", **meta_kw)
    return _annotate(result, **meta_kw)

def _convert_async_function_def(node):
    return _convert_function_def(node, is_async=True)

def _convert_arguments(args_node):
    params = [Symbol(a.arg) for a in args_node.args]
    if args_node.vararg:
        params.append(Symbol("&" + args_node.vararg.arg))
    if args_node.kwarg:
        params.append(Symbol("&&" + args_node.kwarg.arg))
    return params

def _convert_body(stmts):
    """Convert a list of statements into a (begin ...) or single form."""
    forms = [_convert(s) for s in stmts]
    if len(forms) == 1:
        return forms[0]
    return [Symbol("begin")] + forms

def _convert_if(node):
    test = _convert(node.test)
    then = _convert_body(node.body)
    if node.orelse:
        els = _convert_body(node.orelse)
        return _annotate([Symbol("if"), test, then, els],
                         python_type="If", **_loc(node))
    return _annotate([Symbol("when"), test, then],
                     python_type="If", **_loc(node))

def _convert_while(node):
    test = _convert(node.test)
    body = _convert_body(node.body)
    return _annotate(
        [Symbol("while"), test, body],
        python_type="While", lossy=bool(node.orelse), confidence=0.85,
        reason="while/else not supported" if node.orelse else None,
        **_loc(node)
    )

def _convert_for(node):
    # for x in xs: body         →  (for-each (lambda (x) body) xs)
    # for k, v in d.items(): …  →  (for-each (lambda ((tuple k v)) body) xs)
    target = _convert_target(node.target)
    iter_  = _convert(node.iter)
    body   = _convert_body(node.body)
    # Lambda params must be a flat list; wrap tuple targets in a list
    if isinstance(node.target, ast.Name):
        params = [target]
    else:
        params = [target]   # destructuring — Omega's for-each will receive a tuple
    lam = [Symbol("lambda"), params, body]
    return _annotate(
        [Symbol("for-each"), lam, iter_],
        python_type="For", confidence=0.8,
        macro_origin={"python_construct": "for_loop",
                      "lift_strategy": "for-each+lambda",
                      "reversible": True},
        **_loc(node)
    )

def _convert_class_def(node):
    # Classes: partially supported — emit as (class name (bases...) body)
    name  = Symbol(node.name)
    bases = [_convert(b) for b in node.bases]
    body  = [_convert(s) for s in node.body]
    return _annotate(
        [Symbol("class"), name, bases] + body,
        python_type="ClassDef", lossy=True, confidence=0.4,
        reason="Python class semantics not fully representable in Lisp IR",
        **_loc(node)
    )

def _convert_import(node):
    # import foo, bar
    # → (import-native "foo" foo)   if foo is a known stdlib module
    # → (import "foo" foo)          otherwise (treated as a file module)
    forms = []
    for alias in node.names:
        name    = alias.name
        binding = Symbol(alias.asname or alias.name.replace(".", "_"))
        form_op = Symbol("import-native") if _is_stdlib(name) else Symbol("import")
        forms.append(_annotate(
            [form_op, name, binding],
            python_type="Import", confidence=0.9, **_loc(node)
        ))
    return forms[0] if len(forms) == 1 else [Symbol("begin")] + forms

def _convert_import_from(node):
    # from mod import name [as alias]
    # → (import-from "mod" "name" alias)   always — interpreter handles resolution
    mod = node.module or ""
    forms = []
    for alias in node.names:
        binding = Symbol(alias.asname or alias.name)
        forms.append(_annotate(
            [Symbol("import-from"), mod, alias.name, binding],
            python_type="ImportFrom", confidence=0.9, **_loc(node)
        ))
    return forms[0] if len(forms) == 1 else [Symbol("begin")] + forms

# ── stdlib detection ──────────────────────────────────────────────────────
# Mirrors the set in ModuleResolver._PYTHON_STDLIB so transpiler and
# interpreter agree on what is "native" vs "file".  Kept as a plain set
# here so python_to_lisp2.py has no dependency on the interpreter.

_PYTHON_STDLIB_NAMES = {
    "sys", "os", "re", "math", "json", "hashlib", "shutil",
    "traceback", "functools", "itertools", "operator", "copy",
    "collections", "io", "abc", "types", "typing",
    "pathlib", "glob", "fnmatch", "tempfile", "stat",
    "string", "textwrap", "unicodedata", "codecs",
    "time", "datetime", "calendar",
    "struct", "array", "heapq", "bisect", "queue",
    "threading", "multiprocessing", "subprocess", "signal",
    "socket", "ssl", "http", "urllib", "email", "html",
    "random", "statistics", "decimal", "fractions",
    "contextlib", "dataclasses", "enum", "weakref",
    "inspect", "dis", "ast", "tokenize", "importlib",
    "unittest", "logging", "warnings", "pprint",
    "platform", "uuid", "base64", "binascii", "csv",
    "sqlite3", "pickle", "shelve", "configparser",
    "argparse", "getopt", "getpass",
    "numpy", "pandas", "scipy", "matplotlib",
    "requests", "flask", "django", "fastapi",
    "pytest", "hypothesis",
    "prompt_toolkit",
}

def _is_stdlib(name: str) -> bool:
    """True if the top-level module name is a known stdlib / native module."""
    return name.split(".")[0] in _PYTHON_STDLIB_NAMES

def _convert_raise(node):
    if node.exc:
        return _annotate(
            [Symbol("error!"), _convert(node.exc)],
            python_type="Raise", **_loc(node)
        )
    return _annotate([Symbol("re-raise")], python_type="Raise",
                     lossy=True, confidence=0.5, **_loc(node))

def _convert_try(node):
    body     = _convert_body(node.body)
    handlers = [[Symbol("handler"),
                 Symbol(h.type.id if isinstance(h.type, ast.Name) and h.type else "Exception"),
                 Symbol(h.name or "_"),
                 _convert_body(h.body)]
                for h in node.handlers]
    result = [Symbol("try"), body] + handlers
    return _annotate(result, python_type="Try", lossy=True, confidence=0.6,
                     reason="exception handling approximated", **_loc(node))

def _convert_assert(node):
    test = _convert(node.test)
    msg  = _convert(node.msg) if node.msg else "assertion failed"
    return _annotate(
        [Symbol("assert"), test, msg],
        python_type="Assert", **_loc(node)
    )

def _convert_delete(node):
    targets = [_convert_target(t) for t in node.targets]
    return _annotate(
        [Symbol("delete!")] + targets,
        python_type="Delete", lossy=True, confidence=0.5,
        reason="delete has no direct Lisp equivalent", **_loc(node)
    )

def _convert_global(node):
    names = [Symbol(n) for n in node.names]
    return _annotate(
        [Symbol("global")] + names,
        python_type="Global", lossy=True, confidence=0.5, **_loc(node)
    )

def _convert_nonlocal(node):
    names = [Symbol(n) for n in node.names]
    return _annotate(
        [Symbol("nonlocal")] + names,
        python_type="Nonlocal", lossy=True, confidence=0.5, **_loc(node)
    )

def _convert_pass(node):
    return Symbol("None")

def _convert_break(node):
    return _annotate([Symbol("break")], python_type="Break",
                     lossy=True, confidence=0.3,
                     reason="break has no Lisp equivalent")

def _convert_continue(node):
    return _annotate([Symbol("continue")], python_type="Continue",
                     lossy=True, confidence=0.3,
                     reason="continue has no Lisp equivalent")

def _convert_with(node):
    # with expr as name: body  →  (with expr name body)
    items = [[_convert(i.context_expr),
              Symbol(i.optional_vars.id) if isinstance(i.optional_vars, ast.Name) else Symbol("_")]
             for i in node.items]
    body  = _convert_body(node.body)
    return _annotate(
        [Symbol("with")] + items + [body],
        python_type="With", lossy=True, confidence=0.5,
        reason="context managers not natively supported", **_loc(node)
    )


# ── Expression handlers ───────────────────────────────────────────────────

def _convert_constant(node):
    v = node.value
    if v is None:   return Symbol("None")
    if v is True:   return Symbol("true")
    if v is False:  return Symbol("false")
    if isinstance(v, (int, float)): return v
    if isinstance(v, str): return v   # plain str — StringLiteral at eval time
    if isinstance(v, bytes):
        return _annotate([Symbol("bytes"), str(v)], lossy=True, confidence=0.7,
                         reason="bytes literal approximated")
    return _annotate([Symbol("constant"), repr(v)], lossy=True, confidence=0.6)

def _convert_name(node):
    return Symbol(node.id)

def _convert_name_constant(node):
    # Python <3.8 compat
    v = node.value
    if v is None:  return Symbol("None")
    if v is True:  return Symbol("true")
    if v is False: return Symbol("false")
    return Symbol(str(v))

def _convert_num(node):      return node.n   # Python <3.8 compat
def _convert_str(node):      return node.s   # Python <3.8 compat
def _convert_bytes(node):
    return _annotate([Symbol("bytes"), str(node.s)], lossy=True, confidence=0.7)

def _convert_binop(node):
    op  = _binop_sym(node.op)
    lhs = _convert(node.left)
    rhs = _convert(node.right)
    return _annotate([op, lhs, rhs], python_type="BinOp", **_loc(node))

def _convert_unaryop(node):
    if isinstance(node.op, ast.Not):
        return _annotate([Symbol("not"), _convert(node.operand)],
                         python_type="UnaryOp", **_loc(node))
    if isinstance(node.op, ast.USub):
        return _annotate([Symbol("-"), _convert(node.operand)],
                         python_type="UnaryOp", **_loc(node))
    if isinstance(node.op, ast.UAdd):
        return _convert(node.operand)
    if isinstance(node.op, ast.Invert):
        return _annotate([Symbol("bit-not"), _convert(node.operand)],
                         lossy=True, confidence=0.7, python_type="UnaryOp")
    return _annotate([Symbol("unary"), _convert(node.operand)],
                     lossy=True, python_type="UnaryOp")

def _convert_boolop(node):
    op     = Symbol("and") if isinstance(node.op, ast.And) else Symbol("or")
    values = [_convert(v) for v in node.values]
    result = values[0]
    for v in values[1:]:
        result = [op, result, v]
    return _annotate(result, python_type="BoolOp", **_loc(node))

def _convert_compare(node):
    # a < b < c  →  (and (< a b) (< b c))
    ops = [_cmpop_sym(op) for op in node.ops]
    coms = [_convert(c) for c in [node.left] + node.comparators]
    pairs = [[ops[i], coms[i], coms[i+1]] for i in range(len(ops))]
    if len(pairs) == 1:
        return _annotate(pairs[0], python_type="Compare", **_loc(node))
    result = [Symbol("and")] + [_annotate(p, python_type="Compare") for p in pairs]
    return _annotate(result, python_type="Compare", **_loc(node))

def _convert_call(node):
    func = _convert(node.func)
    args = [_convert(a) for a in node.args]
    # Keyword arguments → wrapped as (kw name val)
    kwargs = [[Symbol("kw"), Symbol(kw.arg or "**"), _convert(kw.value)]
              for kw in node.keywords]
    all_args = args + kwargs
    result = [func] + all_args
    lossy  = bool(kwargs)
    return _annotate(result, python_type="Call", lossy=lossy,
                     confidence=0.9 if not lossy else 0.7,
                     reason="keyword arguments approximated as (kw name val)" if lossy else None,
                     **_loc(node))

def _convert_attribute(node):
    obj  = _convert(node.value)
    attr = Symbol(node.attr)
    return _annotate(
        [Symbol("getattr"), obj, attr],
        python_type="Attribute", confidence=0.85,
        reason="attribute access approximated as getattr", **_loc(node)
    )

def _convert_subscript(node):
    obj   = _convert(node.value)
    slice_ = _convert(node.slice)
    return _annotate([Symbol("get"), obj, slice_],
                     python_type="Subscript", **_loc(node))

def _convert_index(node):
    # Python <3.9 compat
    return _convert(node.value)

def _convert_slice(node):
    start = _convert(node.lower) if node.lower else Symbol("None")
    stop  = _convert(node.upper) if node.upper else Symbol("None")
    step  = _convert(node.step)  if node.step  else Symbol("None")
    return _annotate([Symbol("slice"), start, stop, step],
                     python_type="Slice", lossy=True, confidence=0.7)

def _convert_ifexp(node):
    # x if cond else y  →  (if cond x y)
    return _annotate(
        [Symbol("if"), _convert(node.test),
         _convert(node.body), _convert(node.orelse)],
        python_type="IfExp", **_loc(node)
    )

def _convert_lambda(node):
    params = _convert_arguments(node.args)
    body   = _convert(node.body)
    return _annotate(
        [Symbol("lambda"), params, body],
        python_type="Lambda", **_loc(node)
    )

def _convert_list(node):
    elems = [_convert(e) for e in node.elts]
    return _annotate([Symbol("list")] + elems, python_type="List", **_loc(node))

def _convert_tuple(node):
    elems = [_convert(e) for e in node.elts]
    return _annotate([Symbol("tuple")] + elems, python_type="Tuple",
                     confidence=0.85, reason="tuple approximated as list")

def _convert_set(node):
    elems = [_convert(e) for e in node.elts]
    return _annotate([Symbol("set")] + elems, python_type="Set",
                     lossy=True, confidence=0.7)

def _convert_dict(node):
    pairs = []
    for k, v in zip(node.keys, node.values):
        if k is None:  # **spread
            pairs.append([Symbol("**spread"), _convert(v)])
        else:
            pairs.append([Symbol("pair"), _convert(k), _convert(v)])
    return _annotate([Symbol("dict")] + pairs, python_type="Dict",
                     confidence=0.85, **_loc(node))

def _convert_list_comp(node):
    # [expr for x in xs if cond]
    # →  (map (lambda (x) expr) (filter (lambda (x) cond) xs))
    elt     = _convert(node.elt)
    result  = _convert_comprehension(elt, node.generators)
    return _annotate(result, python_type="ListComp", confidence=0.8,
                     macro_origin={"python_construct": "list_comprehension",
                                   "lift_strategy": "map+filter+lambda",
                                   "reversible": False},
                     **_loc(node))

def _convert_comprehension(body, generators):
    if not generators:
        return body
    gen    = generators[0]
    target = _convert(gen.target)
    iter_  = _convert(gen.iter)
    rest   = generators[1:]
    inner  = _convert_comprehension(body, rest)
    if gen.ifs:
        cond    = _combine_ands([_convert(c) for c in gen.ifs])
        filt    = [Symbol("filter"), [Symbol("lambda"), [target], cond], iter_]
        result  = [Symbol("map"),   [Symbol("lambda"), [target], inner], filt]
    else:
        result  = [Symbol("map"),   [Symbol("lambda"), [target], inner], iter_]
    return result

def _combine_ands(conds):
    if len(conds) == 1: return conds[0]
    return [Symbol("and")] + conds

def _convert_dict_comp(node):
    key  = _convert(node.key)
    val  = _convert(node.value)
    result = _convert_comprehension([Symbol("pair"), key, val], node.generators)
    return _annotate([Symbol("dict-from-pairs"), result],
                     python_type="DictComp", lossy=True, confidence=0.6,
                     macro_origin={"python_construct": "dict_comprehension",
                                   "lift_strategy": "dict-from-pairs+map",
                                   "reversible": False})

def _convert_set_comp(node):
    elt    = _convert(node.elt)
    result = _convert_comprehension(elt, node.generators)
    return _annotate([Symbol("set-from-list"), result],
                     python_type="SetComp", lossy=True, confidence=0.6)

def _convert_generator_exp(node):
    elt    = _convert(node.elt)
    result = _convert_comprehension(elt, node.generators)
    return _annotate([Symbol("stream")] + [result],
                     python_type="GeneratorExp", lossy=True, confidence=0.5,
                     reason="generator approximated as eager stream")

def _convert_starred(node):
    return _annotate([Symbol("*spread"), _convert(node.value)],
                     python_type="Starred", lossy=True, confidence=0.6)

def _convert_joined_str(node):
    # f"hello {name}"  →  (string-append "hello " name)
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(v.value)
        elif isinstance(v, ast.FormattedValue):
            parts.append(_convert(v.value))
        else:
            parts.append(_convert(v))
    return _annotate([Symbol("string-append")] + parts,
                     python_type="JoinedStr", confidence=0.85,
                     macro_origin={"python_construct": "f-string",
                                   "lift_strategy": "string-append",
                                   "reversible": True})

def _convert_await(node):
    return _annotate([Symbol("await"), _convert(node.value)],
                     python_type="Await", lossy=True, confidence=0.4,
                     reason="async/await not supported in synchronous Lisp IR")

def _convert_yield(node):
    val = _convert(node.value) if node.value else Symbol("None")
    return _annotate([Symbol("yield"), val],
                     python_type="Yield", lossy=True, confidence=0.4,
                     reason="generators not natively supported")

def _convert_yield_from(node):
    return _annotate([Symbol("yield-from"), _convert(node.value)],
                     python_type="YieldFrom", lossy=True, confidence=0.3)


# ── Op symbol helpers ─────────────────────────────────────────────────────

def _binop_sym(op):
    return {
        ast.Add:    Symbol("+"),  ast.Sub:    Symbol("-"),
        ast.Mult:   Symbol("*"),  ast.Div:    Symbol("/"),
        ast.FloorDiv: Symbol("//"), ast.Mod:  Symbol("mod"),
        ast.Pow:    Symbol("**"), ast.MatMult: Symbol("@"),
        ast.LShift: Symbol("<<"), ast.RShift: Symbol(">>"),
        ast.BitOr:  Symbol("|"),  ast.BitAnd: Symbol("&"),
        ast.BitXor: Symbol("^"),
    }.get(type(op), Symbol("?"))

def _cmpop_sym(op):
    return {
        ast.Eq:    Symbol("="),  ast.NotEq:  Symbol("not="),
        ast.Lt:    Symbol("<"),  ast.LtE:    Symbol("<="),
        ast.Gt:    Symbol(">"),  ast.GtE:    Symbol(">="),
        ast.Is:    Symbol("is"), ast.IsNot:  Symbol("is-not"),
        ast.In:    Symbol("in"), ast.NotIn:  Symbol("not-in"),
    }.get(type(op), Symbol("?"))


# ── Handler dispatch table ────────────────────────────────────────────────

_HANDLERS = {
    # Statements
    "Module":           _convert_module,
    "Expr":             _convert_expr_stmt,
    "Assign":           _convert_assign,
    "AugAssign":        _convert_aug_assign,
    "AnnAssign":        _convert_ann_assign,
    "Return":           _convert_return,
    "FunctionDef":      _convert_function_def,
    "AsyncFunctionDef": _convert_async_function_def,
    "If":               _convert_if,
    "While":            _convert_while,
    "For":              _convert_for,
    "ClassDef":         _convert_class_def,
    "Import":           _convert_import,
    "ImportFrom":       _convert_import_from,
    "Raise":            _convert_raise,
    "Try":              _convert_try,
    "Assert":           _convert_assert,
    "Delete":           _convert_delete,
    "Global":           _convert_global,
    "Nonlocal":         _convert_nonlocal,
    "Pass":             _convert_pass,
    "Break":            _convert_break,
    "Continue":         _convert_continue,
    "With":             _convert_with,
    # Expressions
    "Constant":         _convert_constant,
    "Name":             _convert_name,
    "NameConstant":     _convert_name_constant,  # Python <3.8
    "Num":              _convert_num,             # Python <3.8
    "Str":              _convert_str,             # Python <3.8
    "Bytes":            _convert_bytes,
    "BinOp":            _convert_binop,
    "UnaryOp":          _convert_unaryop,
    "BoolOp":           _convert_boolop,
    "Compare":          _convert_compare,
    "Call":             _convert_call,
    "Attribute":        _convert_attribute,
    "Subscript":        _convert_subscript,
    "Index":            _convert_index,           # Python <3.9
    "Slice":            _convert_slice,
    "IfExp":            _convert_ifexp,
    "Lambda":           _convert_lambda,
    "List":             _convert_list,
    "Tuple":            _convert_tuple,
    "Set":              _convert_set,
    "Dict":             _convert_dict,
    "ListComp":         _convert_list_comp,
    "DictComp":         _convert_dict_comp,
    "SetComp":          _convert_set_comp,
    "GeneratorExp":     _convert_generator_exp,
    "Starred":          _convert_starred,
    "JoinedStr":        _convert_joined_str,
    "Await":            _convert_await,
    "Yield":            _convert_yield,
    "YieldFrom":        _convert_yield_from,
}


# ── Pretty printer ────────────────────────────────────────────────────────

def pretty_print(node, indent=0, show_meta=True) -> str:
    """
    Convert a Lisp AST node to a readable S-expression string.

    Meta annotations are shown as '; @conf=0.8 lossy' comments
    on the same line when show_meta=True.
    """
    pad   = "  " * indent
    pad1  = "  " * (indent + 1)

    # Unwrap __meta__ annotations
    meta  = None
    inner = node
    if isinstance(node, list) and len(node) == 3 and node[0] == "__meta__":
        meta  = node[1]
        inner = node[2]

    meta_comment = ""
    if meta and show_meta:
        parts = []
        c = meta.get("confidence", 1.0)
        if c < 1.0: parts.append(f"conf={c:.1f}")
        if meta.get("lossy"): parts.append("lossy")
        if meta.get("reason"): parts.append(f"reason=\"{meta['reason']}\"")
        if meta.get("macro_origin"):
            mo = meta["macro_origin"]
            parts.append(f"lift={mo.get('lift_strategy','?')}")
        if parts:
            meta_comment = "  ; @" + " ".join(parts)

    # Scalar atoms
    if inner is None:           return pad + "None" + meta_comment
    if isinstance(inner, bool): return pad + ("true" if inner else "false") + meta_comment
    if isinstance(inner, int):  return pad + str(inner) + meta_comment
    if isinstance(inner, float):return pad + str(inner) + meta_comment
    if isinstance(inner, str) and not isinstance(inner, Symbol):
        escaped = inner.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return pad + f'"{escaped}"' + meta_comment
    if isinstance(inner, Symbol):
        return pad + str(inner) + meta_comment

    # Lists
    if not isinstance(inner, list) or len(inner) == 0:
        return pad + "()" + meta_comment

    head = inner[0]
    tail = inner[1:]

    # Compact one-liners for short forms
    flat = _try_flat(inner)
    if flat and len(flat) + len(pad) <= 80:
        return pad + flat + meta_comment

    # Multi-line: head on first line, args indented
    head_str = pretty_print(head, 0, show_meta=False)
    if not tail:
        return f"{pad}({head_str}){meta_comment}"

    lines = [f"{pad}({head_str}"]
    for item in tail:
        lines.append(pretty_print(item, indent + 1, show_meta))
    lines[-1] += ")"
    if meta_comment:
        lines[0] += meta_comment
    return "\n".join(lines)


def _try_flat(node) -> str:
    """Try to render node as a single line; return None if too complex."""
    if node is None:            return "None"
    if isinstance(node, bool):  return "true" if node else "false"
    if isinstance(node, int):   return str(node)
    if isinstance(node, float): return str(node)
    if isinstance(node, str) and not isinstance(node, Symbol):
        escaped = node.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{escaped}"'
    if isinstance(node, Symbol): return str(node)
    if not isinstance(node, list): return None

    # Unwrap meta
    if len(node) == 3 and node[0] == "__meta__":
        return _try_flat(node[2])

    parts = [_try_flat(x) for x in node]
    if any(p is None for p in parts): return None
    result = "(" + " ".join(parts) + ")"
    return result if len(result) <= 60 else None


# ── Summary / stats ───────────────────────────────────────────────────────

def get_stats(node) -> dict:
    """Walk a Lisp AST and collect lossiness statistics."""
    total = lossy = 0
    min_conf = 1.0

    def walk(n):
        nonlocal total, lossy, min_conf
        if isinstance(n, list):
            if len(n) == 3 and n[0] == "__meta__":
                total += 1
                m = n[1]
                if m.get("lossy"): lossy += 1
                c = m.get("confidence", 1.0)
                if c < min_conf: min_conf = c
                walk(n[2])
            else:
                for x in n:
                    walk(x)
    walk(node)
    return {
        "total_annotated": total,
        "lossy_nodes":     lossy,
        "min_confidence":  round(min_conf, 2),
        "lossiness_pct":   round(100 * lossy / max(total, 1), 1),
    }


# ── File-level API ────────────────────────────────────────────────────────

# The exact comment lines written by transpiler11.ol at the top of every
# generated .py file.  We use these to detect and strip the prelude.
_PRELUDE_MARKERS = (
    "# ── Omega Runtime Prelude",
    "# Generated by transpiler",
)
_PRELUDE_END_MARKER = "# ── Transpiled functions"


def strip_omega_prelude(source: str) -> str:
    """
    If `source` is a file generated by transpile-file (i.e. it starts with
    the Omega runtime prelude), strip the prelude block and return only the
    user-defined function definitions that follow.

    If the source doesn't look like a generated file, return it unchanged.
    """
    lines = source.splitlines()
    # Check if this looks like a generated Omega output file
    first_real = next((l for l in lines if l.strip()), "")
    if not any(first_real.startswith(m) for m in _PRELUDE_MARKERS):
        return source   # not a generated file, lift everything

    # Find the end-of-prelude marker and return only what follows
    for i, line in enumerate(lines):
        if line.startswith(_PRELUDE_END_MARKER):
            # Skip the marker line itself and any blank lines after it
            rest = lines[i + 1:]
            while rest and not rest[0].strip():
                rest = rest[1:]
            return "\n".join(rest)

    return source  # marker not found — lift everything


def transpile_file(input_path: str, output_path: str = None,
                   show_meta=True, strip_prelude=True) -> str:
    """
    Read a .py file, transpile it to Lisp, return the pretty-printed string.

    strip_prelude (default True):
        If the file is a generated Omega output file (starts with the Omega
        Runtime Prelude header), strip the prelude before lifting so only the
        user-defined functions are included.  This prevents `class`, `getattr`,
        `isinstance` etc. from appearing in the lifted Lisp — those are Python
        infrastructure, not Omega code.

    If output_path is given, also write the result to that file.
    """
    with open(input_path) as f:
        source = f.read()
    if strip_prelude:
        source = strip_omega_prelude(source)
    ast_node = py_to_lisp(source)
    output   = pretty_print(ast_node, show_meta=show_meta)
    stats    = get_stats(ast_node)
    header   = (
        f"; Transpiled from: {input_path}\n"
        f"; Nodes: {stats['total_annotated']}  "
        f"Lossy: {stats['lossy_nodes']} ({stats['lossiness_pct']}%)  "
        f"Min confidence: {stats['min_confidence']}\n\n"
    )
    result = header + output
    if output_path:
        with open(output_path, "w") as f:
            f.write(result)
    return result


def transpile_source(source: str, show_meta=True, strip_prelude=True) -> str:
    """Transpile a Python source string directly to a Lisp string."""
    if strip_prelude:
        source = strip_omega_prelude(source)
    return pretty_print(py_to_lisp(source), show_meta=show_meta)


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 python_to_lisp.py <input.py> [output.ol]")
        sys.exit(1)
    out = sys.argv[2] if len(sys.argv) > 2 else None
    result = transpile_file(sys.argv[1], out)
    print(result)
    if out:
        stats = get_stats(py_to_lisp(open(sys.argv[1]).read()))
        print(f"\n; Written to {out}")
        print(f"; Stats: {stats}")
