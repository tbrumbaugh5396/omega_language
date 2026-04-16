; py_lift.ol — Python → Omega Lisp lifting bridge
;
; Converts Python source files to Omega Lisp using python_to_lisp4.py.
; Requires python_to_lisp4.py in the same directory (or on sys.path).
;
; Usage:
;   (load "py_lift.ol")
;   (py->lisp "myfile.py")             ; print annotated Lisp, return path
;   (py->lisp-clean "myfile.py")       ; print clean Lisp (no confidence annotations)
;   (py-ast "myfile.py")               ; return lifted source as a string
;   (py-save "myfile.py" "out.ol")     ; lift and write .ol file, return path
;   (py-stats "myfile.py")             ; return lossiness report string
;   (py-roundtrip "src.py" "rt.py")    ; Python -> Lisp -> Python round-trip
;
; Round-trip note:
;   Full automated round-trip requires transpiler.ol loaded first:
;     (load "transpiler.ol")
;     (load "py_lift.ol")
;     (py-roundtrip "myfile.py" "myfile_rt.py")
;
; Fixes vs py_lift.ol:
;   - (defined? sym) now works (built-in special form added to interpreter)
;   - load works correctly inside function bodies
;   - ensure-bootstrap is idempotent even when called from multiple contexts

(module PyLift

  (define _bootstrap-done false)

  (define (ensure-bootstrap)
    (if _bootstrap-done
        '()
        (begin
          (py-exec "import sys, os; sys.path.insert(0, os.getcwd())")
          (py-exec "from python_to_lisp4 import (py_to_lisp, pretty_print, transpile_source, transpile_file as _py_transpile_file, get_stats, strip_omega_prelude)")
          (set! _bootstrap-done true)
          '())))

  ; ── py->lisp ─────────────────────────────────────────────────────────
  ; Lift .py file → print annotated Lisp (with confidence scores), return path

  (define (py->lisp path)
    (ensure-bootstrap)
    (display (py-eval (string-append "_py_transpile_file('" path "', show_meta=True)")))
    path)

  ; ── py->lisp-clean ───────────────────────────────────────────────────
  ; Lift .py file → print clean Lisp (no confidence annotations), return path

  (define (py->lisp-clean path)
    (ensure-bootstrap)
    (display (py-eval (string-append "_py_transpile_file('" path "', show_meta=False)")))
    path)

  ; ── py-ast ───────────────────────────────────────────────────────────
  ; Return lifted source as a string (for further processing or loading)

  (define (py-ast path)
    (ensure-bootstrap)
    (py-eval (string-append "_py_transpile_file('" path "', show_meta=False)")))

  ; ── py-save ──────────────────────────────────────────────────────────
  ; Lift .py → write annotated .ol file, return ol-path

  (define (py-save py-path ol-path)
    (ensure-bootstrap)
    (write-file ol-path
      (py-eval (string-append "_py_transpile_file('" py-path "', show_meta=True)")))
    ol-path)

  ; ── py-save-clean ────────────────────────────────────────────────────
  ; Lift .py → write clean (no annotations) .ol file, return ol-path

  (define (py-save-clean py-path ol-path)
    (ensure-bootstrap)
    (write-file ol-path
      (py-eval (string-append "_py_transpile_file('" py-path "', show_meta=False)")))
    ol-path)

  ; ── py-stats ─────────────────────────────────────────────────────────
  ; Return lossiness statistics as a string:
  ;   total_annotated, lossy_nodes, lossiness_pct, min_confidence

  (define (py-stats path)
    (ensure-bootstrap)
    (py-eval (string-append
      "(lambda s: str(get_stats(py_to_lisp(s))))(open('" path "').read())")))

  ; ── py-source->lisp ──────────────────────────────────────────────────
  ; Lift a Python source string → Lisp string
  ; show-meta: true = include confidence annotations, false = clean output

  (define (py-source->lisp source show-meta)
    (ensure-bootstrap)
    (let ((tmp "__py_lift_tmp__.py"))
      (write-file tmp source)
      (py-eval (string-append
        "transpile_source(open('" tmp "').read(), show_meta="
        (if show-meta "True" "False") ")"))))

  ; ── py-roundtrip ─────────────────────────────────────────────────────
  ; Full Python → Lisp → Python round-trip.
  ;
  ; Steps:
  ;   1. Lift src-path → clean Lisp (Omega runtime prelude stripped automatically)
  ;   2. Write the Lisp to "<src-path>.roundtrip.ol"
  ;   3. Load the .ol into the current REPL environment
  ;   4. If transpile-file is defined (transpiler.ol loaded), write dst-path
  ;      Otherwise return a message with next steps
  ;
  ; For full automation load transpiler12.ol first:
  ;   (load "transpiler.ol")
  ;   (load "py_lift.ol")
  ;   (py-roundtrip "myfile.py" "myfile_rt.py")

  (define (py-roundtrip src-path dst-path)
    (ensure-bootstrap)
    (let* ((lisp-src  (py-eval (string-append
                         "_py_transpile_file('"
                         src-path
                         "', show_meta=False, strip_prelude=True)")))
           (ol-path   (string-append src-path ".roundtrip.ol")))
      (write-file ol-path lisp-src)
      (load ol-path)
      (if (defined? 'transpile-file)
          (begin
            (transpile-file dst-path (module-exports PythonTranspiler))
            dst-path)
          (string-append
            "Wrote " ol-path
            " — load transpiler.ol then call: "
            "(transpile-file \"" dst-path "\" '(fn1 fn2 ...))"))))

) ; end module PyLift

(open PyLift)
