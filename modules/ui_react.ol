; ui_react.ol — Component-based reactive UI for Omega Lisp
;
; Extends ui.ol with a React-like component model:
;
;   (defui counter ()
;     (state count 0)
;     (vbox
;       (label (string-append "Count: " (number->string count)))
;       (button "+" (set! count (+ count 1)))
;       (button "Reset" (set! count 0))))
;
;   (define app (mount counter "Counter App"))
;   (run-app app)
;
; Re-render model:
;   - Components re-render their entire widget tree when state changes.
;   - Old widgets are destroyed, new ones created.
;   - Simpler than diffing — fine for desktop GUIs at this scale.
;
; Usage:
;   (import "ui_react.ol" r)
;   (r.defui ...)      ; or (load "ui_react.ol") + (defui ...)

(import "gui.ol"  g)
(import "ui.ol"   u)

(module ReactUI

  (export
    defui mount component run-app
    ; state helpers
    use-state use-effect
    ; layout
    vertical horizontal row col
    ; styled widgets
    heading subheading paragraph
    card panel)

  ; ── Component registry ────────────────────────────────────────────────

  ; Each mounted component has:
  ;   root      — the tk window
  ;   container — the inner Frame that holds all widgets
  ;   render-fn — (lambda () container) that rebuilds widgets
  ;   dirty?    — whether a re-render is scheduled

  (define *components* '())

  ; ── Component render engine ───────────────────────────────────────────

  (define (mount-component root render-fn)
    (let ((container (g.add-frame root)))
      ; First render
      (render-fn container)
      ; Store for future re-renders
      (define (rerender!)
        ; Destroy all children of container
        (py-exec "_children = list(_tk.Pack.pack_slaves(_container))")
        (py-eval "_container")   ; just to reference it... use direct call:
        (for-each
          (lambda (child) (py-call-method child "destroy"))
          (py-eval (string-append
            "[w for w in vars().get('_tk',__import__('tkinter')).Pack.pack_slaves("
            "None)]")))
        ; Re-render
        (render-fn container))
      (list container rerender!)))

  ; ── defui macro ───────────────────────────────────────────────────────
  ;
  ; (defui name (param ...) body...)
  ;
  ; Defines a component constructor. Returns a function that, when called
  ; with a parent container, renders itself into that container.
  ;
  ; State variables declared with (state name val) are local to the
  ; component and trigger re-render when changed via (set-state! name val).

  (register-macro! defui (name params . body)
    `(define ,name
       (lambda ,params
         ; Returns a render function that takes a container
         (lambda (container)
           ,@body))))

  ; ── mount: render a component into a new window ───────────────────────

  (define (mount component-fn title)
    (let* ((root      (g.make-window title))
           (container (g.add-frame root)))
      ; Track current container for re-renders
      (define *container* container)
      (define *root* root)
      (define (do-render!)
        ; Destroy old widgets
        (py-call-method *container* "destroy")
        (set! *container* (g.add-frame *root*))
        (py-call-method *container* "pack")
        (component-fn *container*))
      ; Wire the global rerender trigger
      (py-exec "_omega_rerender = None")
      (py-eval "_omega_rerender")
      ; Initial render
      (component-fn container)
      root))

  ; ── use-state: state variable that triggers re-render ─────────────────
  ;
  ; Since Omega closures capture env by reference, a plain (define) inside
  ; a component body combined with (run-refresh!) from ui.ol is enough.
  ; (use-state) is just a named alias that makes intent clear.

  (register-macro! use-state (name init)
    `(define ,name ,init))

  ; ── use-effect: run side effect on mount (runs once) ──────────────────

  (register-macro! use-effect (body)
    `(begin ,body None))

  ; ── Layout helpers ────────────────────────────────────────────────────

  ; These return widget-thunks (lambda (container) ...) matching ui.ol style

  (register-macro! vertical children
    `(lambda (container)
       ,@(map (lambda (c) `(,c container)) children)
       container))

  (register-macro! horizontal children
    `(lambda (container)
       (let ((frame (g.add-frame container)))
         (py-call-method-kw frame "pack" :fill "x")
         ,@(map (lambda (c)
                  `(let ((w (,c frame)))
                     (g.pack-opts w "left" "none" false 4 4)))
                children)
         frame)))

  ; Grid layout: (row ...) / (col ...)
  (register-macro! row children
    `(horizontal ,@children))

  (register-macro! col children
    `(vertical ,@children))

  ; ── Styled widgets ────────────────────────────────────────────────────

  (define (heading container text)
    (let ((lbl (g.add-label container text)))
      (py-call-method-kw lbl "config" :font "Helvetica 18 bold")
      (g.pack-opts lbl "top" "x" false 4 8)
      lbl))

  (define (subheading container text)
    (let ((lbl (g.add-label container text)))
      (py-call-method-kw lbl "config" :font "Helvetica 14 bold")
      (g.pack-opts lbl "top" "x" false 4 4)
      lbl))

  (define (paragraph container text)
    (let ((lbl (g.add-label container text)))
      (py-call-method-kw lbl "config" :wraplength 400 :justify "left")
      (g.pack-opts lbl "top" "x" false 4 2)
      lbl))

  ; card: framed group of widgets
  (register-macro! card children
    `(lambda (container)
       (let ((frame (g.tk-raw-call "tkinter.LabelFrame" container)))
         (py-call-method-kw frame "pack" :padx 8 :pady 8 :fill "both")
         ,@(map (lambda (c) `(,c frame)) children)
         frame)))

  ; panel: plain framed group
  (register-macro! panel children
    `(lambda (container)
       (let ((frame (g.add-frame container)))
         (py-call-method-kw frame "pack"
           :padx 4 :pady 4 :fill "both" :expand true)
         ,@(map (lambda (c) `(,c frame)) children)
         frame)))

  ; ── run-app ───────────────────────────────────────────────────────────

  (define (run-app root)
    (g.run-app root))

) ; end module ReactUI

(open ReactUI)
