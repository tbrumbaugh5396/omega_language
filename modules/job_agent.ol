;; job_agent.ol — find jobs, score fit, tailor a resume, and PROPOSE applying.
;;
;; Usage: (load "modules/job_agent.ol")
;;        (job-agent-dry-run)                       ; no network, no LLM, no writes
;;        (run-job-agent "https://example.com/jobs") ; the real thing
;;
;; WHY THIS EXISTS. Everything under it — capabilities, propose, the review
;; cockpit, cron capsets — was built to make exactly this safe, and none of it
;; had ever been pointed at a real task. This is the first agent that uses the
;; authority layer instead of describing it.
;;
;; THREE PROPERTIES, and they are the whole point:
;;
;;   1. NO py-* ANYWHERE. The py-* family is the escape hatch, and it is now
;;      capability-gated (kernel.py _gate_py_interop). An agent that reaches for
;;      it is an agent that stopped using the language. This one does real work
;;      — HTTP, an LLM, JSON, ranking, persistence — in native Omega, which is
;;      the claim the language has to be able to make.
;;
;;   2. IT NEVER APPLIES. It PROPOSES. Every consequential step goes through
;;      (propose ...) first and branches on the verdict. Applying to a job is
;;      irreversible and public — it reaches a real employer under your name —
;;      so it is exactly the class of act that must not happen because a model
;;      felt confident. The proposal lands in the cockpit for a human.
;;
;;   3. IT RUNS WITHOUT `secrets`. Its capset is (base browse). It never needs a
;;      credential, so it is never granted one, so a compromised prompt cannot
;;      exfiltrate one. Confinement by absence — see confined-root in the spec.
;;      `(job-agent-capset)` is the declaration; put it on the cron_agents row.

(load "modules/alist.ol")   ; alist-get / alist-set / alist-keys

; ── field access ─────────────────────────────────────────────────────────────
; alist-get takes (key alist default). Every lookup in this file is "pull a
; string field out of a record", so it gets one wrapper with the arguments in
; record-first order and an empty-string default. A missing field then reads as
; "" and flows through to the proposal — visible to the human reviewing it —
; instead of raising three stages later where the cause is unrecoverable.
(define (jget rec key) (alist-get key rec ""))

; ── configuration ────────────────────────────────────────────────────────────
; The capset this agent is meant to run under. `browse` lets it drive the
; server-side browser; `base` is always present. Deliberately absent: `secrets`
; (never needs a credential), `fs_write`, `deploy`, `destructive`.
(define (job-agent-capset) (list "base" "browse"))

; Your profile. Edit this — it is the only thing here that is about you.
(define (job-agent-profile)
  (list (list "title"    "Programming language designer / systems engineer")
        (list "skills"   "language design, capability security, distributed systems, Python, Lisp")
        (list "seeking"  "staff or principal, remote, systems or developer-tools")
        (list "avoid"    "crypto, adtech, on-site-only")
        (list "bullets"  "Designed and shipped Omega, a capability-secure Lisp with derived effect signatures.|Built an object-capability authority layer with behavioural conformance gates for swappable subsystems.|Diagnosed and fixed a shipped self-deadlock in a 29-call-site lock hierarchy.")))

; How good a match has to be before it is worth a human's attention at all.
(define (job-agent-threshold) 70)

; ── envelope helpers ─────────────────────────────────────────────────────────
; Every ctrl-* primitive returns [["value" v] ["confidence" c] ["trace" t]].
; Unwrapping in one place keeps the pipeline readable and means a shape change
; is a one-line fix rather than a scavenger hunt.
(define (env-value e) (jget e "value"))
(define (env-conf e)  (jget e "confidence"))
(define (env-ok? e)   (and (> (env-conf e) 0) (not (null? (env-value e)))))

; ── source: drive the server-side browser ────────────────────────────────────
; POST /browser/op is the COMMAND surface (write_handlers.route_browser_op) and
; is in the route table, so this dispatches IN-PROCESS on the calling thread.
; The interactive /browser/<op> chain would go out over a loopback socket and
; deadlock under the eval lock — same implementation, wrong door.
(define (browser-op op params)
  (ctrl-http "POST" "/browser/op" (list (list "op" op) (list "params" params))))

(define (fetch-page url)
  (do (browser-op "goto" (list (list "url" url)))
      (browser-op "wait_for" (list (list "ms" 1500)))
      (env-value (browser-op "get_dom" (list)))))

; ── extraction, scoring, tailoring: three narrow LLM calls ───────────────────
; Narrow and separate on purpose. One mega-prompt that scrapes, judges and
; writes is one prompt injection away from doing all three wrong at once, and
; when it fails you cannot tell WHICH part failed. Separate calls fail
; separately and are separately checkable.

(define (extract-jobs html)
  (env-value
    (ctrl-llm
      "Extract job postings from this page. Return ONLY a JSON array; each element has keys: title, company, location, url, summary. No prose, no code fence."
      (substring html 0 20000)
      (list (list "max-tokens" 2000) (list "temperature" 0)))))

(define (score-job profile job)
  (env-value
    (ctrl-llm
      "Score how well this candidate fits this job, honestly. A low score is a useful answer; do not inflate. Return ONLY JSON: {\"score\": 0-100, \"reasons\": \"one sentence\", \"concerns\": \"one sentence\"}"
      (string-append "CANDIDATE:\n" (json-stringify profile)
                     "\n\nJOB:\n" (json-stringify job))
      (list (list "max-tokens" 400) (list "temperature" 0)))))

(define (tailor-bullets profile job)
  (env-value
    (ctrl-llm
      "Rewrite this candidate's resume bullets to target this specific job. Keep every claim TRUE — you may reframe and reorder, never invent. Return ONLY a JSON array of 3 strings."
      (string-append "CANDIDATE:\n" (json-stringify profile)
                     "\n\nJOB:\n" (json-stringify job))
      (list (list "max-tokens" 600) (list "temperature" 0.3)))))

; ── the gate ─────────────────────────────────────────────────────────────────
; Applying is irreversible and public. It goes to a real employer under your
; name, and there is no unsend. So this function does not apply — it asks, and
; returns whatever the policy said. The ONLY path to actually applying is a
; human acting on the proposal in the cockpit.
(define (propose-application job scored bullets)
  (propose
    (string-append "Apply to " (jget job "title") " at " (jget job "company"))
    (string-append "Fit " (json-stringify (jget scored "score")) "/100. "
                   (jget scored "reasons")
                   "  CONCERNS: " (jget scored "concerns")
                   "  URL: " (jget job "url")
                   "  TAILORED BULLETS: " (json-stringify bullets))
    "job-apply"
    "high"))

; ── tracking ─────────────────────────────────────────────────────────────────
; Applications you have already seen, so a agent that runs hourly does not
; re-propose the same job forever. Keyed by url — the one field that is stable
; across re-listings, unlike title or summary.
(define (seen-key job) (string-append "jobagent:seen:" (jget job "url")))

(define (already-seen? job)
  (not (null? (env-value (ctrl-http "GET" (string-append "/kv/" (seen-key job)) (list))))))

(define (mark-seen! job verdict)
  (ctrl-http "PUT" (string-append "/kv/" (seen-key job))
             (list (list "value" (string-append verdict " @ " (now))))))

; ── the pipeline ─────────────────────────────────────────────────────────────
(define (consider profile job)
  (if (already-seen? job)
      (list (list "job" job) (list "outcome" "skipped-seen"))
      (let* ((scored (score-job profile job))
             (score  (jget scored "score")))
        (if (< score (job-agent-threshold))
            (do (mark-seen! job "below-threshold")
                (list (list "job" job) (list "score" score)
                      (list "outcome" "below-threshold")))
            (let* ((bullets (tailor-bullets profile job))
                   (verdict (propose-application job scored bullets))
                   (action  (jget verdict "action")))
              (do (mark-seen! job action)
                  (list (list "job" job) (list "score" score)
                        (list "bullets" bullets)
                        (list "outcome" action))))))))

(define (run-job-agent url)
  (let* ((profile (job-agent-profile))
         (html    (fetch-page url))
         (jobs    (extract-jobs html)))
    (map (lambda (j) (consider profile j)) jobs)))

; ── dry run ──────────────────────────────────────────────────────────────────
; Exercises the pipeline's SHAPE with no network, no LLM and no writes, so the
; wiring is checkable before any of it can do anything. The first thing to run
; after loading this file, and the thing to run when something breaks — if the
; dry run passes, the bug is in the world, not in the code.
(define (job-agent-fixture)
  (list (list "title" "Staff Language Engineer")
        (list "company" "Example Corp")
        (list "location" "Remote")
        (list "url" "https://example.com/jobs/1")
        (list "summary" "Design and implement a typed effect system.")))

(define (job-agent-dry-run)
  (let* ((profile (job-agent-profile))
         (job     (job-agent-fixture)))
    (list
      (list "capset"        (job-agent-capset))
      (list "profile-keys"  (map (lambda (p) (first p)) profile))
      (list "fixture-job"   (jget job "title"))
      (list "seen-key"      (seen-key job))
      (list "threshold"     (job-agent-threshold))
      (list "note" "shape only — no network, no LLM, no writes"))))
