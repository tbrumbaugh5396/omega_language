; weather.ol — Real-time weather dashboard in Omega Lisp
;
; Usage: (load "weather.ol")
;        (start-weather)
;
; Requires: ui.ol, gui.ol (loaded transitively)
;           Python packages: requests (pip install requests)

(load "ui.ol")    ; brings make-window, make-label, make-button,
                  ; make-hbox, make-vbox, run-app, run-refresh! into scope

; ── Python setup ─────────────────────────────────────────────────────────
(py-exec "import requests, urllib.parse, time")

; Model: all mutable state lives in a Python dict for easy py-eval access
(py-exec "
weather_model = {
  'city':    'London',
  'temp':    '--',
  'feels':   '--',
  'desc':    'Ready',
  'humidity':'--',
  'wind':    '--',
  'status':  'Ready',
  'updated': 'Never'
}
")

; ── Model helpers ─────────────────────────────────────────────────────────

(define (model-get key)
  (py-eval (string-append "weather_model['" key "']")))

(define (model-set! key value)
  ; Escape single quotes in value to avoid breaking the Python expression
  (py-exec
    (string-append "weather_model['" key "'] = "
                   (py-eval (string-append "repr('" value "')")))))

; ── Fetch ─────────────────────────────────────────────────────────────────

(define (fetch-weather!)
  (model-set! "status" "Fetching...")
  (run-refresh!)
  ; Use try/except in Python so network errors don't crash the app
  (py-exec "
try:
    _city   = weather_model['city']
    _safe   = urllib.parse.quote(_city)
    _url    = f'https://wttr.in/{_safe}?format=j1'
    _r      = requests.get(_url, timeout=8).json()
    _cur    = _r['current_condition'][0]
    weather_model['temp']     = _cur['temp_C']
    weather_model['feels']    = _cur['FeelsLikeC']
    weather_model['humidity'] = _cur['humidity']
    weather_model['wind']     = _cur['windspeedKmph']
    weather_model['desc']     = _cur['weatherDesc'][0]['value']
    weather_model['status']   = 'OK'
    weather_model['updated']  = time.strftime('%I:%M:%S %p')
except Exception as e:
    weather_model['status']   = f'Error: {str(e)[:40]}'
    weather_model['updated']  = time.strftime('%I:%M:%S %p')
")
  (run-refresh!))

; ── View ──────────────────────────────────────────────────────────────────

(define (weather-view)
  (make-vbox
    (list
      ; City header
      (make-label (lambda ()
        (string-append "📍 " (model-get "city"))))

      ; Status bar
      (make-label (lambda ()
        (string-append "Status: " (model-get "status"))))

      ; Main temperature
      (make-label (lambda ()
        (string-append "🌡  Temperature:   "
                       (model-get "temp") " °C  "
                       "(feels " (model-get "feels") " °C)")))

      ; Condition description
      (make-label (lambda ()
        (string-append "☁  Condition:     " (model-get "desc"))))

      ; Humidity
      (make-label (lambda ()
        (string-append "💧 Humidity:      " (model-get "humidity") " %")))

      ; Wind
      (make-label (lambda ()
        (string-append "💨 Wind:          " (model-get "wind") " km/h")))

      ; Last updated
      (make-label (lambda ()
        (string-append "🕐 Last update:   " (model-get "updated"))))

      ; Controls row
      (make-hbox
        (list
          (make-button "🔄 Refresh"
            (lambda () (fetch-weather!)))

          (make-button "London"
            (lambda ()
              (model-set! "city" "London")
              (fetch-weather!)))

          (make-button "New York"
            (lambda ()
              (model-set! "city" "New York")
              (fetch-weather!)))

          (make-button "Tokyo"
            (lambda ()
              (model-set! "city" "Tokyo")
              (fetch-weather!))))))))

; ── Entry point ───────────────────────────────────────────────────────────

(define (start-weather)
  (let ((app (make-window "Omega Weather" (list (weather-view)))))
    ; Fetch weather immediately on launch
    (fetch-weather!)
    (run-app app)))

(print "Weather app loaded. Run (start-weather) to open the window.")
