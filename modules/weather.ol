(py-exec "import requests")
(py-exec "import urllib.parse") ;; NEW: Safely handles spaces in city names
(py-exec "import time")         ;; NEW: For adding timestamps

;; Initialize Model in Python
(py-exec "m = {'city': 'London', 'temp': '--', 'status': 'Ready', 'updated': 'Never'}")

(import "ui.ol" ui)
(import "std.ol" std)

;; ── 1. UPDATE ────────────────────────────────────────────────────────
(define (update key value)
  (py-exec (string-append "m['" key "'] = '" value "'"))
  (ui.run-refresh!))

;; ── 2. VIEW ──────────────────────────────────────────────────────────
(define (weather-view)
  (ui.make-vbox 
    (list
      ;; Status Indicator
      (ui.make-label (lambda () (string-append "Status: " (py-eval "m['status']"))))
      
      ;; Main Temperature Display
      (ui.make-label (lambda () 
        (string-append "Current temp in " (py-eval "m['city']") ": " (py-eval "m['temp']") "°C")))
      
      ;; Timestamp
      (ui.make-label (lambda () (string-append "Last update: " (py-eval "m['updated']"))))
      
      (ui.make-hbox
        (list
          (ui.make-button "Refresh" 
            (lambda ()
              ;; 1. Set status to loading
              (update "status" "Fetching weather...")
              
              ;; 2. Fetch the data safely
              (let* ((city (py-eval "m['city']"))
                     ;; Safely encode spaces (e.g., "New York" -> "New%20York")
                     (safe-city (py-eval (string-append "urllib.parse.quote('" city "')")))
                     (url  (string-append "https://wttr.in/" safe-city "?format=j1"))
                     (cmd  (string-append "requests.get('" url "').json()['current_condition'][0]['temp_C']"))
                     (res  (py-eval cmd))
                     (now  (py-eval "time.strftime('%I:%M:%S %p')")))
                
                ;; 3. Update the rest of the model
                (update "temp" res)
                (update "updated" now)
                (update "status" "Success!")))))))))

;; ── 3. RUNTIME ───────────────────────────────────────────────────────
(define (start-weather)
  (let ((app (ui.make-window "Omega Dash" (list (weather-view)))))
    (ui.run-app app)))

(start-weather)