; ui.ol — Declarative UI DSL for Omega Lisp (function-based, no macros)
;
; Uses plain functions instead of macros so prelude restoration
; never overrides the DSL with stale definitions.
;
; (load "ui.ol")
;
; Usage:
;   (load "ui.ol")
;   (define count 0)
;   (define app (make-window "Counter"
;     (list
;       (make-label (lambda () (string-append "Count: " (number->string count))))
;       (make-hbox (list
;         (make-button "−" (lambda () (set! count (- count 1))))
;         (make-button "+" (lambda () (set! count (+ count 1)))))))))
;   (run-app app)

(import "gui.ol" g)

(module UI

  (export
    ; window builder
    make-window run-app
    ; widget builders — each returns a (lambda (parent) widget) thunk
    make-label make-button make-hbox make-vbox
    make-entry make-separator make-spacer
    ; refresh system
    register-refresh! run-refresh! clear-refreshers!
    ; DSL macro sugar (re-registered fresh on every load)
    ui window label button hbox vbox entry separator spacer state)

  ; ── Refresh registry ─────────────────────────────────────────────────

  (define *refreshers* '())

  (define (register-refresh! f)
    (set! *refreshers* (cons f *refreshers*)))

  (define (run-refresh!)
    (for-each (lambda (f) (f)) *refreshers*))

  (define (clear-refreshers!)
    (set! *refreshers* '()))

  ; ── Utilities ────────────────────────────────────────────────────────

  (define (any->string x)
    (cond ((null? x)   "")
          ((= x true)  "true")
          ((= x false) "false")
          ((number? x) (number->string x))
          ((string? x) x)
          (else        "")))

  ; ── Core widget builders (plain functions) ────────────────────────────

  ; make-window: build a root Tk window, apply each widget thunk to it
  ; children = list of (lambda (parent) widget)
  (define (make-window title children)
    (let ((root (g.make-window title)))
      (py-call-method-kw root "minsize" :width 300 :height 80)
      (for-each (lambda (child) (child root)) children)
      root))

  ; make-label: live label bound to a thunk that returns the text
  ; get-text-fn = (lambda () string-or-number)
  (define (make-label get-text-fn)
    (lambda (parent)
      (let* ((sv  (g.make-string-var))
             (lbl (py-call-kw "tkinter.Label" parent
                    :textvariable sv :anchor "w")))
        (py-call-method-kw lbl "pack" :fill "x" :padx 6 :pady 3)
        (g.set-var sv (any->string (get-text-fn)))
        (register-refresh!
          (lambda ()
            (g.set-var sv (any->string (get-text-fn)))))
        lbl)))

  ; make-button: button that runs action-fn then refreshes all labels
  (define (make-button text action-fn)
    (lambda (parent)
      (let ((btn (py-call-kw "tkinter.Button" parent
                   :text text :width 6
                   :command (py-wrap-callback
                               (lambda ()
                                 (action-fn)
                                 (run-refresh!))))))
        (py-call-method-kw btn "pack" :side "left" :padx 2 :pady 2)
        btn)))

  ; make-hbox: horizontal row of widget thunks
  (define (make-hbox children)
    (lambda (parent)
      (let ((frame (py-call "tkinter.Frame" parent)))
        (py-call-method-kw frame "pack" :fill "x" :padx 2 :pady 1)
        (for-each (lambda (child) (child frame)) children)
        frame)))

  ; make-vbox: vertical stack of widget thunks
  (define (make-vbox children)
    (lambda (parent)
      (let ((frame (py-call "tkinter.Frame" parent)))
        (py-call-method-kw frame "pack" :fill "both" :expand true)
        (for-each (lambda (child) (child frame)) children)
        frame)))

  ; make-entry: text entry; sv is a StringVar from (g.make-string-var)
  (define (make-entry sv)
    (lambda (parent)
      (let ((e (py-call-kw "tkinter.Entry" parent :textvariable sv :width 28)))
        (py-call-method-kw e "pack" :side "left" :padx 4 :pady 4)
        e)))

  ; make-separator: thin horizontal or vertical divider
  (define (make-separator orient)
    (lambda (parent)
      (let ((sep (py-call-kw "tkinter.Frame" parent :height 2 :bg "#bbbbbb")))
        (if (equal? orient "horizontal")
            (py-call-method-kw sep "pack" :fill "x" :padx 4 :pady 4)
            (py-call-method-kw sep "pack" :fill "y" :side "left" :padx 4))
        sep)))

  ; make-spacer: blank padding
  (define (make-spacer px)
    (lambda (parent)
      (let ((f (py-call "tkinter.Frame" parent)))
        (py-call-method-kw f "pack" :padx px)
        f)))

  ; run-app: enter tkinter mainloop
  (define (run-app root)
    (g.run-app root))

  ; ── Macro sugar ───────────────────────────────────────────────────────
  ;
  ; These macros expand to calls to the plain functions above.
  ; They are re-registered every time ui.ol is loaded, so a stale prelude
  ; can never break them — the functions are what matter, not the macros.
  ;
  ; (window "Title" c1 c2 ...) → (make-window "Title" (list c1 c2 ...))
  ; (label expr)               → (make-label (lambda () expr))
  ; (button "T" action)        → (make-button "T" (lambda () action))
  ; (hbox c1 c2 ...)           → (make-hbox (list c1 c2 ...))
  ; (vbox c1 c2 ...)           → (make-vbox (list c1 c2 ...))

  (register-macro! ui     (B) B)
  (register-macro! window (T . C) `(make-window ,T (list ,@C)))
  (register-macro! label  (E)     `(make-label (lambda () ,E)))
  (register-macro! button (T A)   `(make-button ,T (lambda () ,A)))
  (register-macro! hbox   (. C)   `(make-hbox (list ,@C)))
  (register-macro! vbox   (. C)   `(make-vbox (list ,@C)))
  (register-macro! entry  (S)     `(make-entry ,S))
  (register-macro! separator (O)  `(make-separator ,O))
  (register-macro! spacer (P)     `(make-spacer ,P))
  (register-macro! state  (N V)   `(define ,N ,V))

) ; end module UI

(open UI)
