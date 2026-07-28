;; watchdog.ol — an agent that monitors the node's OTHER agents.
;;
;; Usage: save modules/alist.ol, then this file, via the Files page.
;;        (watchdog-dry-run)          ; shape only — nothing touched
;;        (watchdog-cron (list ) "")  ; one real pass
;;
;; THE SECOND AGENT, built to the seven-part skeleton in
;; docs/WRITING_AN_AGENT.md, and deliberately different from job_agent.ol on
;; every axis that matters:
;;
;;   * NO LLM anywhere. Its judgment is deterministic rules. The judgment SLOT
;;     is mandatory; a model in it is not.
;;   * NO browser. Its source is the node's own inspection surface.
;;   * Its capset needs `monitor` — so out of the box IT GETS REFUSED. A
;;     scheduled run's caller resolves to the default grant, which does not
;;     include monitor, and /node/inspect answers capability_denied. That is
;;     the system working. The fix is an explicit grant to this principal:
;;
;;       INSERT INTO capability_grants (space_id, principal, caps_json, granted_by, granted_at)
;;       VALUES ('default', 'cron:watchdog', '["base","monitor"]', 'you', <now>);
;;
;;     (or the cap_grant agent tool). Until then every run reports outcome
;;     "unauthorized" — honestly, without crashing, without pretending.

; SELF-CONTAINED — no (load ...). The scheduled-job executor stitches this
; file's own symbols as the eval preamble; a load of another space file is not
; resolvable there. GOTCHA: an agent that runs on a schedule should carry its
; helpers inline (or depend only on primitives), or it will pass every REPL
; test and fail on its first real firing.
(define (wd-alist-get key alist default)
  (let ((entry (filter (lambda (p) (equal? (first p) key)) alist)))
    (if (null? entry) default (second (first entry)))))

; jget — shape-dispatching accessor (alists and host dicts print identically;
; alist-get silently misses on a dict — see docs/WRITING_AN_AGENT.md).
(define (jget rec key)
  (if (list? rec)
      (wd-alist-get key rec "")
      (let ((v (get rec key ""))) (if (null? v) "" v))))

; ── 1. config ────────────────────────────────────────────────────────────────
; How long a job may sit past its next_fire_at before that itself is a finding.
(define (watchdog-overdue-seconds) 3600)

; ── 2. capset — declared before the code was written ─────────────────────────
; `monitor` because watching other agents IS monitoring — the same category
; that gates a human doing it in #agents → Inspect. Deliberately absent:
; browse (no web), send (it reports via proposals, it does not message anyone),
; and everything stronger.
(define (watchdog-capset) (list "base" "monitor"))

; ── 3. source — the node's own WHERE lens, in-process ────────────────────────
; /node/inspect is in the route table, so ctrl-http dispatches it on this
; thread. The SAME authority check that gates a human gates this call.
(define (observe-node)
  (env-value (ctrl-http "GET" "/node/inspect" (list))))

(define (node-ok? obs)
  (equal? (jget (jget obs "body") "ok") true))

(define (node-denied? obs)
  (equal? (jget (jget obs "body") "capability_denied") true))

(define (node-subjects obs)
  (jget (jget obs "body") "subjects"))

; ── 4. judgment — deterministic rules, each returning a finding or () ────────
(define (check-error subj)
  (if (equal? (jget subj "last_status") "error")
      (string-append "last run of " (jget subj "principal") " ERRORED")
      ()))

(define (check-overdue subj)
  (let ((nf (jget subj "next_fire_at")))
    (if (and (number? nf) (> nf 0) (equal? (jget subj "enabled") true)
             (> (- (now) nf) (watchdog-overdue-seconds)))
        (string-append (jget subj "principal") " is overdue — next_fire_at "
                       "passed more than an hour ago (scheduler stuck?)")
        ())))

(define (check-undeclared subj)
  (if (equal? (jget subj "capabilities") "")
      (string-append (jget subj "principal") " runs UNDECLARED — it gets the "
                     "default grant; declare :capabilities on its define-cron")
      ()))

(define (findings-for subj)
  (filter (lambda (f) (not (null? f)))
          (list (check-error subj) (check-overdue subj)
                (check-undeclared subj))))

; ── 5. the gate — findings become proposals, never direct action ─────────────
; Consequence "low": a watchdog note destroys nothing, so the autonomy policy
; is allowed to auto-apply it. Compare job_agent's "high", which always stops
; for a human. Same gate, different dial — that is the tiering.
(define (propose-finding f)
  (propose (string-append "Watchdog: " (substring f 0 60))
           f "watchdog-note" "low"))

; ── 6. memory — one proposal per (subject, firing), not per run ──────────────
(define (finding-key f) (string-append "watchdog:seen:" f))
(define (finding-seen? f) (not (equal? (kv-get (finding-key f) "") "")))
(define (mark-finding! f v) (kv-set (finding-key f) v))

(define (raise-finding f)
  (if (finding-seen? f)
      (list (list "finding" f) (list "outcome" "already-raised"))
      (let ((verdict (propose-finding f)))
        (begin (mark-finding! f (jget verdict "action"))
               (list (list "finding" f)
                     (list "outcome" (jget verdict "action")))))))

; ── 7. entry points + dry run ────────────────────────────────────────────────
(define (watchdog-pass)
  (let ((obs (observe-node)))
    (if (node-denied? obs)
        ; Refused is an ANSWER, not an error. Say what is missing and stop —
        ; and mark nothing seen, so findings raise once authority exists.
        (list (list "outcome" "unauthorized")
              (list "note" "grant [\"base\",\"monitor\"] to cron:watchdog in capability_grants"))
        (if (node-ok? obs)
            (let ((fs (apply append (map findings-for (node-subjects obs)))))
              (if (null? fs)
                  (list (list "outcome" "all-healthy")
                        (list "subjects" (length (node-subjects obs))))
                  (map raise-finding fs)))
            (list (list "outcome" "observe-failed")
                  (list "note" (substring (json-stringify obs) 0 200)))))))

(define (watchdog-cron params body) (watchdog-pass))

(define-deployment "watchdog" :name "Watchdog"
  :description "Monitors the node's agents; proposes findings")

; Every 30 minutes. :capabilities is what the RUN is granted (tool gating);
; the capability_grants row is what lets its OBSERVATION through may_address.
; Two declarations today — a known seam, noted in AGENT_INSPECTION_DESIGN.md.
(define-cron "*/30 * * * *" watchdog-cron
  :name "watchdog"
  :description "Agent health sweep — errors, overdue schedules, undeclared capsets"
  :capabilities "base monitor")

(define (watchdog-dry-run)
  (let ((fake (list (list "principal" "cron:example") (list "kind" "scheduled_job")
                    (list "capabilities" "") (list "enabled" true)
                    (list "last_status" "error") (list "next_fire_at" 0))))
    (list (list "capset" (watchdog-capset))
          (list "findings-on-fixture" (findings-for fake))
          (list "note" "shape only — no network, no writes"))))
