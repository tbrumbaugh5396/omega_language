; gui_examples.ol — Example GUI apps for Omega Lisp
;
; (load "gui_examples.ol")  then  (run-counter) etc.
;
; Each example reloads ui.ol to ensure fresh macro/function definitions,
; overriding any stale macros from the prelude.

; ── bootstrap ────────────────────────────────────────────────────────────
; Always reload ui.ol fresh — this ensures the DSL functions and macros
; are correct regardless of what's in the autosave prelude.
(load "ui.ol")


; ── Example 1: Counter ───────────────────────────────────────────────────

(define (run-counter)
  (clear-refreshers!)
  (define count 0)
  (define app
    (make-window "Counter"
      (list
        (make-label  (lambda () (string-append "Count: " (number->string count))))
        (make-hbox (list
          (make-button "−"     (lambda () (set! count (- count 1))))
          (make-button "Reset" (lambda () (set! count 0)))
          (make-button "+"     (lambda () (set! count (+ count 1)))))))))
  (run-app app))


; ── Example 2: To-Do List ────────────────────────────────────────────────

(define (run-todo)
  (clear-refreshers!)
  (define todos '())
  (define sv    None)
  (define typed "")

  (define (make-entry-widget parent)
    (set! sv (g.make-string-var))
    (g.trace-var sv (lambda () (set! typed (g.get-var sv))))
    (let ((e (py-call-kw "tkinter.Entry" parent :textvariable sv :width 28)))
      (py-call-method-kw e "pack" :side "left" :padx 4 :pady 4)
      e))

  (define (add!)
    (if (and (not (null? sv)) (> (length typed) 0))
        (begin
          (set! todos (append todos (list typed)))
          (set! typed "")
          (g.set-var sv ""))
        None))

  (define (list-text)
    (if (null? todos)
        "(empty — type and press Add)"
        (apply string-append
          (map (lambda (t) (string-append "  • " t "\n")) todos))))

  (define app
    (make-window "To-Do List"
      (list
        (make-hbox (list
          make-entry-widget
          (make-button "Add" (lambda () (add!)))))
        (make-label (lambda () (list-text))))))

  (run-app app))


; ── Example 3: Calculator ────────────────────────────────────────────────

(define (run-calculator)
  (clear-refreshers!)
  (define disp    "0")
  (define pending None)
  (define op      None)
  (define fresh   true)

  (define (digit d)
    (if fresh
        (begin (set! disp (number->string d)) (set! fresh false))
        (if (equal? disp "0")
            (set! disp (number->string d))
            (set! disp (string-append disp (number->string d))))))

  (define (operation o)
    (set! pending (string->number disp))
    (set! op o)
    (set! fresh true))

  (define (equals!)
    (if (not (null? pending))
        (let* ((rhs    (string->number disp))
               (result (cond ((equal? op "+") (+ pending rhs))
                             ((equal? op "-") (- pending rhs))
                             ((equal? op "×") (* pending rhs))
                             ((equal? op "÷") (if (= rhs 0) "ERR" (/ pending rhs)))
                             (else rhs))))
          (set! disp (number->string result))
          (set! pending None) (set! op None) (set! fresh true))
        None))

  (define (clear!)
    (set! disp "0") (set! pending None) (set! op None) (set! fresh true))

  (define (row . btns) (make-hbox btns))

  (define app
    (make-window "Calculator"
      (list
        (make-label (lambda () disp))
        (make-hbox (list (make-button "7" (lambda () (digit 7)))
                         (make-button "8" (lambda () (digit 8)))
                         (make-button "9" (lambda () (digit 9)))
                         (make-button "÷" (lambda () (operation "÷")))))
        (make-hbox (list (make-button "4" (lambda () (digit 4)))
                         (make-button "5" (lambda () (digit 5)))
                         (make-button "6" (lambda () (digit 6)))
                         (make-button "×" (lambda () (operation "×")))))
        (make-hbox (list (make-button "1" (lambda () (digit 1)))
                         (make-button "2" (lambda () (digit 2)))
                         (make-button "3" (lambda () (digit 3)))
                         (make-button "−" (lambda () (operation "-")))))
        (make-hbox (list (make-button "C" (lambda () (clear!)))
                         (make-button "0" (lambda () (digit 0)))
                         (make-button "=" (lambda () (equals!)))
                         (make-button "+" (lambda () (operation "+"))))))))

  (run-app app))


; ── Example 4: Canvas animation ──────────────────────────────────────────
;
; Module-level state. _cv-cb is set inside run-canvas-demo (not at load time)
; so reloading the file doesn't create a stale callback reference.

(define _cv-root   None)
(define _cv-canvas None)
(define _cv-angle  0)
(define _cv-cb     None)   ; assigned in run-canvas-demo before first tick

(define (_cv-tick)
  (set! _cv-angle (mod (+ _cv-angle 6) 360))
  (py-call-method _cv-canvas "delete" "all")
  (py-call-method-kw _cv-canvas "create_rectangle" 20 20 180 100
    :fill "lightblue" :outline "navy")
  (py-call-method-kw _cv-canvas "create_oval" 200 20 380 100
    :fill "lightyellow" :outline "orange")
  (py-call-method-kw _cv-canvas "create_text" 200 295
    :text "Omega Lisp Canvas" :font "Helvetica 13 bold")
  (let* ((cx 200) (cy 180) (r 70)
         (d  _cv-angle)
         (x  (py-eval (string-append
               "int(200+70*__import__('math').cos(__import__('math').radians("
               (number->string d) ")))")))
         (y  (py-eval (string-append
               "int(180+70*__import__('math').sin(__import__('math').radians("
               (number->string d) ")))"))))
    (py-call-method-kw _cv-canvas "create_oval"
      (- cx r) (- cy r) (+ cx r) (+ cy r) :outline "#888")
    (py-call-method-kw _cv-canvas "create_line"
      cx cy x y :fill "royalblue" :width 3)
    (py-call-method-kw _cv-canvas "create_oval"
      (- x 6) (- y 6) (+ x 6) (+ y 6) :fill "tomato" :outline "tomato"))
  ; Use _cv-cb which was set before the first tick in run-canvas-demo
  (py-call-method _cv-root "after" 50 _cv-cb))

(define (run-canvas-demo)
  (set! _cv-root   (g.make-window "Canvas Demo"))
  (set! _cv-canvas (g.add-canvas _cv-root 400 320))
  (set! _cv-angle  0)
  ; CRITICAL: set _cv-cb BEFORE calling _cv-tick for the first time.
  ; This way every subsequent after() reuses the same Python callable.
  (set! _cv-cb (py-wrap-callback _cv-tick))
  (_cv-tick)
  (g.run-app _cv-root))


; ── Example 5: Components ────────────────────────────────────────────────

(define (run-component-demo)
  (clear-refreshers!)

  (define (make-counter lbl-text init)
    (define val init)
    (lambda (parent)
      ((make-label (lambda () (string-append lbl-text ": " (number->string val)))) parent)
      ((make-hbox (list
         (make-button (string-append "− " lbl-text) (lambda () (set! val (- val 1))))
         (make-button (string-append "+ " lbl-text) (lambda () (set! val (+ val 1))))))
       parent)))

  (define app
    (make-window "Components Demo"
      (list
        (make-counter "Counter A" 0)
        (make-separator "horizontal")
        (make-counter "Counter B" 10)
        (make-separator "horizontal")
        (make-counter "Counter C" -5))))

  (run-app app))


; ── Entry point ──────────────────────────────────────────────────────────

(print "GUI examples loaded.")
(print "Run: (run-counter)  (run-todo)  (run-calculator)")
(print "     (run-canvas-demo)  (run-component-demo)")
