; transpiler12.ol — Omega Lisp → Python transpiler (v1 complete)
;
; Handles all v1 primitives:
;   Core forms: define, lambda, if, cond, let/let*/letrec, begin, quote
;   Arithmetic, comparison, boolean operators
;   Type predicates: null?, number?, integer?, string?, symbol?, list?, bool?, lambda?
;   v1 additions: eq?, equal?, fold, memoize, memoized?, trace-calls, traced?
;                 module?, module-name, module-origin, module-exports, module-lookup
;   Output: runtime prelude + transpiled defs written to .py file
;
; Usage:
;   (load "transpiler12.ol")
;   (define (square x) (* x x))
;   (transpile-file "square.py" '(square))
;   ;=> writes square.py
;   ;   python3 -c "import square; print(square.square(5))"  → 25

(module PythonTranspiler

  ; ── helpers ─────────────────────────────────────────────────────────────

  (define (join sep strings)
    (if (null? strings) ""
        (reduce (lambda (acc s) (string-append acc sep s))
                (rest strings)
                (first strings))))

  ; ── name mangling ────────────────────────────────────────────────────────

  (define (python-name sym)
    (let* ((s (symbol->string sym))
           (s (join "_to_" (string-split s "->")))
           (s (join "_"    (string-split s "-")))
           (s (join "_p"   (string-split s "?"))))
      s))

  ; ── core transpiler ─────────────────────────────────────────────────────

  (define (transpile expr)
    (cond
      ((null?           expr)  "None")
      ((bool?           expr)  (if expr "True" "False"))
      ((number?         expr)  (number->string expr))
      ((string-literal? expr)  (string-append "\"" expr "\""))
      ((string?         expr)  (python-name (string->symbol expr)))
      ((symbol?         expr)
       (cond
         ((= expr 'else)  "True")
         ((= expr 'true)  "True")
         ((= expr 'false) "False")
         ((= expr 'None)  "None")
         (else (python-name expr))))
      (else
       (let ((head (first expr))
             (args (rest  expr)))
         (cond
           ((= head 'define)
            (if (list? (second expr))
                (let ((fname (python-name (first (second expr))))
                      (fargs (join ", " (map python-name (rest (second expr)))))
                      (body  (transpile (third expr))))
                  (string-append "def " fname "(" fargs "):\n    return " body))
                (string-append (python-name (second expr)) " = " (transpile (third expr)))))
           ((= head 'lambda)
            (let ((params (first args)) (body (second args)))
              (string-append "lambda " (join ", " (map python-name params)) ": " (transpile body))))
           ((= head 'if)
            (let ((c (transpile (second expr)))
                  (t (transpile (third  expr)))
                  (f (if (null? (nth expr 3)) "None" (transpile (nth expr 3)))))
              (string-append "(" t " if " c " else " f ")")))
           ((= head 'cond)
            (letrec ((cond->py (lambda (clauses)
                        (if (null? clauses) "None"
                            (let ((test (first (first clauses))) (action (second (first clauses))))
                              (if (= test 'else) (transpile action)
                                  (string-append "(" (transpile action) " if " (transpile test)
                                                 " else " (cond->py (rest clauses)) ")")))))))
              (cond->py (rest expr))))
           ((or (= head 'let) (= head 'let*) (= head 'letrec))
            (let ((bindings (second expr)) (body (third expr)))
              (string-append
                "(lambda " (join ", " (map (lambda (b) (python-name (first b))) bindings))
                ": " (transpile body) ")("
                (join ", " (map (lambda (b) (transpile (second b))) bindings)) ")")))
           ((= head 'begin)
            (if (null? (rest args)) (transpile (first args))
                (string-append "(" (join ", " (map transpile args)) ")[-1]")))
           ((= head 'quote)
            (let ((q (first args)))
              (if (symbol? q) (string-append "\"" (symbol->string q) "\"")
                  (if (null? q) "[]" (transpile q)))))
           ((or (= head '+) (= head '-) (= head '*) (= head '/)
                (= head '<) (= head '>) (= head '<=) (= head '>=)
                (= head '=) (= head 'and) (= head 'or))
            (let ((op (cond ((= head '=) "==") ((= head 'and) " and ")
                            ((= head 'or) " or ") (else (symbol->string head)))))
              (string-append "(" (join (string-append " " op " ") (map transpile args)) ")")))
           ((= head 'not)
            (string-append "(not " (transpile (first args)) ")"))
           ((= head 'null?)
            (let ((a (transpile (first args))))
              (string-append "(" a " is None or " a " == [])")))
           ((= head 'number?)
            (let ((a (transpile (first args))))
              (string-append "(isinstance(" a ", (int, float)) and not isinstance(" a ", bool))")))
           ((= head 'integer?)
            (let ((a (transpile (first args))))
              (string-append "(isinstance(" a ", int) and not isinstance(" a ", bool))")))
           ((= head 'string?)
            (let ((a (transpile (first args))))
              (string-append "(isinstance(" a ", str) and not isinstance(" a ", Symbol))")))
           ((= head 'symbol?)  (string-append "(isinstance(" (transpile (first args)) ", Symbol))"))
           ((= head 'list?)    (string-append "(isinstance(" (transpile (first args)) ", list))"))
           ((= head 'bool?)    (string-append "(isinstance(" (transpile (first args)) ", bool))"))
           ((= head 'lambda?)  (string-append "(isinstance(" (transpile (first args)) ", Lambda))"))
           ; ── v1 primitives ────────────────────────────────────────────────
           ((= head 'eq?)
            (string-append "(" (transpile (first args)) " is " (transpile (second args)) ")"))
           ((= head 'equal?)
            (string-append "_structural_equal(" (transpile (first args)) ", " (transpile (second args)) ")"))
           ((= head 'fold)
            ; (fold f init lst) — Scheme-order: accumulates left with init
            (string-append "lisp_fold("
              (transpile (first args)) ", "
              (transpile (second args)) ", "
              (transpile (third args)) ")"))
           ((= head 'memoize)
            (string-append "_make_memoized_wrapper(" (transpile (first args)) ", None)"))
           ((= head 'memoized?)
            (string-append "getattr(" (transpile (first args)) ", '_is_memoized', False)"))
           ((= head 'trace-calls)
            (string-append "_make_traced_wrapper(" (transpile (first args)) ")"))
           ((= head 'traced?)
            (string-append "getattr(" (transpile (first args)) ", '_is_traced', False)"))
           ((= head 'module?)
            (string-append "isinstance(" (transpile (first args)) ", Module)"))
           ((= head 'module-name)
            (string-append "getattr(" (transpile (first args)) ", 'name', None)"))
           ((= head 'module-origin)
            (string-append "getattr(" (transpile (first args)) ", 'origin', None)"))
           ((= head 'module-exports)
            (let ((a (transpile (first args))))
              (string-append "(" a ".public_keys() if isinstance(" a ", Module) else [])")))
           ((= head 'module-lookup)
            (string-append (transpile (first args)) ".lookup(str(" (transpile (second args)) "))"))
           (else
            (string-append (transpile head) "(" (join ", " (map transpile args)) ")"))
           )))))

  ; ── single named function → def block ───────────────────────────────────
  ;
  ; transpile-named:  returns a Python def string (may contain real \n for
  ;                   the def body — correct for top-level functions).
  ;
  ; transpile-named-safe:  same, but escapes any \n that appear *inside*
  ;                   string arguments in the body.  Use this when the output
  ;                   will be embedded inside another Python expression or
  ;                   written to a file as a complete def statement.

  (define (transpile-named sym)
    (let ((f (eval sym)))
      (if (lambda? f)
          (let ((src (get-source f)))
            (if (null? src)
                (string-append "# <no source for " (symbol->string sym) ">")
                (let ((params (second src))
                      (body   (third  src)))
                  ; escape-py-strings fixes any literal \n inside Python string
                  ; arguments in the body (e.g. the ":\n    return " in define).
                  ; Without this, the generated .py file has unterminated strings.
                  (string-append
                    "def " (python-name sym)
                    "(" (join ", " (map python-name params)) "):\n"
                    "    return " (escape-py-strings (transpile body))))))
          (string-append (python-name sym) " = " (transpile f)))))

  ; ── runtime prelude ──────────────────────────────────────────────────────
  ;
  ; The fixed Python block prepended to every emitted module.
  ; Contains all helpers that transpiled Omega code may call.
  ; Matches trans.py's interface exactly so output is compatible.

  (define runtime-prelude "# ── Omega Runtime Prelude ──────────────────────────────────────────────
# Generated by transpiler12.ol. Do not edit manually.

class Symbol(str):
    \"\"\"Omega symbol — an identifier, distinct from string values.\"\"\"
    pass

class StringLiteral(str):
    \"\"\"Omega string literal value.\"\"\"
    pass

def string_literal_p(x):  return isinstance(x, (str, StringLiteral)) and not isinstance(x, Symbol)
def symbol_p(x):           return isinstance(x, Symbol)
def number_p(x):           return isinstance(x, (int, float)) and not isinstance(x, bool)
def list_p(x):             return isinstance(x, list)
def bool_p(x):             return isinstance(x, bool)
def null_p(x):             return x is None or x == []

def first(x):              return x[0]
def second(x):             return x[1]
def third(x):              return x[2] if len(x) > 2 else None
def rest(x):               return x[1:]
def nth(x, i):             return x[i] if len(x) > i else None

def join(sep, items):      return sep.join(str(i) for i in items)
def string_append(*args):  return ''.join(map(str, args))
def symbol_to_string(s):   return str(s)
def string_to_symbol(s):   return Symbol(s)
def number_to_string(x):   return str(x)

def python_name(sym):
    s = str(sym)
    s = '_to_'.join(s.split('->'))
    s = '_'.join(s.split('-'))
    s = '_p'.join(s.split('?'))
    return s

def _structural_equal(a, b):
    if type(a) != type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)): return a == b
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_structural_equal(x, y) for x, y in zip(a, b))
    return a == b

def lisp_fold(f, init, lst):
    acc = init
    for x in lst: acc = f(acc, x)
    return acc

def _make_memoized_wrapper(f, _env=None):
    cache = {}
    def memoized(*args):
        k = tuple(args)
        if k not in cache: cache[k] = f(*args)
        return cache[k]
    memoized._memo = cache; memoized._is_memoized = True; memoized._original = f
    return memoized

def _make_traced_wrapper(f):
    name = getattr(f, '__name__', '?')
    depth = [0]
    def traced(*args):
        print('  ' * depth[0] + f'-> ({name} {\" \".join(repr(a) for a in args)})')
        depth[0] += 1
        result = f(*args)
        depth[0] -= 1
        print('  ' * depth[0] + f'<- {name} = {result!r}')
        return result
    traced._is_traced = True; traced._original = f
    return traced

# ── Transpiled functions ─────────────────────────────────────────────────
")

  ; ── transpile-module ─────────────────────────────────────────────────────
  ;
  ; Returns a complete Python source string.
  ; `syms` may be:
  ;   a quoted list  →  '(square fib factorial)
  ;   a bare symbol  →  'transpile        (single function)
  ;   a list value   →  (list 'a 'b 'c)
  ;
  ; (transpile-module '(square fib))  →  "# ── Omega Runtime...\ndef square..."
  ; (transpile-module 'transpile)     →  "# ── Omega Runtime...\ndef transpile..."

  (define (transpile-module syms)
    ; Normalize: if syms is a symbol (single name), wrap it in a list
    (let ((sym-list (if (symbol? syms) (list syms) syms)))
      (let ((defs (map transpile-named sym-list)))
        (string-append runtime-prelude "\n" (join "\n\n" defs) "\n"))))

  ; ── transpile-file ───────────────────────────────────────────────────────
  ;
  ; Writes a complete Python module to `filename`. Returns the filename.
  ;
  ; Examples:
  ;   (transpile-file "square.py" '(square))      ; list of names
  ;   (transpile-file "square.py" 'square)         ; single name — same result
  ;   (transpile-file "all.py" '(square fib transpile))

  (define (transpile-file filename syms)
    (write-file filename (transpile-module syms)))

) ; end module

(open PythonTranspiler)
