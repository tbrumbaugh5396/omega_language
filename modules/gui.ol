(module GUI
  (export make-window run-app add-label add-button add-frame pack-opts
          make-string-var get-var set-var) ; Added these exports 
  (define (make-window title)
    (let ((root (py-call "tkinter.Tk")))
      (py-call-method root "title" title)
      root))
  (define (run-app root) (py-call-method root "mainloop"))
  (define (add-label parent text)
    (let ((l (py-call "tkinter.Label" parent)))
      (py-call-method-kw l "config" :text text)
      (py-call-method l "pack")
      l))
  (define (add-button parent text cmd)
    (let ((b (py-call "tkinter.Button" parent)))
      (py-call-method-kw b "config" :text text :command (py-wrap-callback cmd))
      (py-call-method b "pack")
      b))
  (define (add-frame parent)
    (let ((f (py-call "tkinter.Frame" parent)))
      (py-call-method f "pack")
      f))
  (define (pack-opts widget side fill expand padx pady)
    (py-call-method-kw widget "pack" :side side :fill fill :expand expand :padx padx :pady pady))

  ;; Reactive Variable Helpers 
  (define (make-string-var)
    (py-call "tkinter.StringVar"))

  (define (get-var sv)
    (py-call-method sv "get"))

  (define (set-var sv val)
    (py-call-method sv "set" val))
)