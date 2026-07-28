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
; TWO RECORD SHAPES, ONE PRINTED FORM. Omega code builds alists — lists of
; (key value) pairs — but host primitives like `propose` return Python dicts, and
; the printer renders BOTH as (("action" "propose") ...). They are not
; interchangeable: alist-get filters over pairs and silently returns its default
; on a dict, while `get` reads a dict and not an alist.
;
; That cost a real bug. consider() read (jget verdict "action") off propose's
; dict, got "", and recorded every gated job with an empty outcome — the
; proposal reached the cockpit correctly, but the agent's own ledger had no idea
; what the gate had decided. Nothing raised; the value just quietly went missing.
;
; So jget dispatches on the shape rather than assuming one.
(define (jget rec key)
  (if (list? rec)
      (alist-get key rec "")
      (let ((v (get rec key))) (if (null? v) "" v))))

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
  (begin (browser-op "goto" (list (list "url" url)))
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

; ── scoring: two implementations, and the result says which one ran ──────────
; The LLM is the least interesting part of this pipeline — it is a black box
; call. The interesting parts (the threshold, the gate, the proposal, the
; seen-ledger) do not need it. So scoring degrades to a local, deterministic
; keyword scorer when no provider is configured, and the record carries a
; "scorer" field saying which ran.
;
; This is not a mock. It is a real second implementation with a real weakness —
; it counts word overlap and cannot read a sentence — and labelling it honestly
; in the output is what keeps that weakness from being mistaken for judgement.
; A human reading a proposal scored "keyword" knows exactly how much to trust it.

; There is no contains? primitive, but str-split gives one for free: splitting a
; haystack on a needle yields more than one part exactly when the needle occurs.
(define (contains? hay needle) (> (length (str-split hay needle)) 1))

; NB: case-SENSITIVE. There is no str-lower primitive, and rather than fake one
; out of 26 str-replace calls this scorer matches literally and says so. It is a
; genuine weakness of the keyword path, which is precisely why the record it
; produces is labelled "keyword" — see the note above score-local.
; `fold`, not `reduce`. This kernel's reduce is (reduce f lst) with no seed —
; passing one makes it read the seed as the list and fail with "expected a list,
; but got int (0)". fold is the Scheme-order (fold f init lst).
(define (count-hits words text)
  (fold (lambda (acc w)
          (if (and (> (string-length w) 3) (contains? text w)) (+ acc 1) acc))
        0 words))

(define (score-local profile job)
  (let* ((hay   (string-append (jget job "title") " "
                               (jget job "summary") " "
                               (jget job "company")))
         (want  (str-split (jget profile "skills") ", "))
         (avoid (str-split (jget profile "avoid") ", "))
         (hits  (count-hits want hay))
         (bad   (count-hits avoid hay))
         (score (- (* hits 18) (* bad 40))))
    (list (list "score" (if (< score 0) 0 (if (> score 100) 100 score)))
          (list "reasons" (string-append "matched " (number->string hits)
                                         " of " (number->string (length want))
                                         " skill terms"))
          (list "concerns" (if (> bad 0)
                               "matches an avoid-term"
                               "keyword scoring cannot read the posting"))
          (list "scorer" "keyword"))))

(define (score-job profile job)
  (let ((e (ctrl-llm
             "Score how well this candidate fits this job, honestly. A low score is a useful answer; do not inflate. Return ONLY JSON: {\"score\": 0-100, \"reasons\": \"one sentence\", \"concerns\": \"one sentence\"}"
             (string-append "CANDIDATE:\n" (json-stringify profile)
                            "\n\nJOB:\n" (json-stringify job))
             (list (list "max-tokens" 400) (list "temperature" 0)))))
    (if (usable? (env-value e))
        (alist-set "scorer" "llm" (env-value e))
        (score-local profile job))))

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

; NATIVE kv, not (ctrl-http "GET" "/kv/..."). The first version of this used
; ctrl-http and it was wrong in two ways at once, which an end-to-end run found
; in one shot and no amount of reading would have:
;
;   * /kv is not in the route table, so the call fell back to a loopback socket,
;     deadlocked against the eval lock, and took 15.12 SECONDS to time out.
;   * the timed-out result was still truthy, so already-seen? answered `true` for
;     every job — the agent would have silently skipped all of them, forever,
;     while looking like it ran fine.
;
; kv-get/kv-set are in-process primitives. Beyond being correct and instant,
; this DELETES a send-class effect from the agent's signature: talking to
; yourself over a socket reads as network egress to the effect deriver, and an
; agent whose capset is (base browse) should not appear to send anything.
(define (already-seen? job)
  (not (equal? (kv-get (seen-key job) "") "")))

(define (mark-seen! job verdict)
  (kv-set (seen-key job) (string-append verdict " @ " (now))))

; ── the pipeline ─────────────────────────────────────────────────────────────
; A stage that returned nothing must STOP the pipeline, not flow an empty value
; into the next stage. The first version read (jget scored "score") straight off
; score-job's result; with no LLM provider configured ctrl-llm returns an
; envelope whose value is `false`, jget tried to filter over it, and the whole
; call died with "'NoneType' object is not iterable" — a message that names
; neither the missing provider nor the stage that failed.
;
; env-ok? existed for exactly this and was not being used. Now a dead stage
; yields an explicit "llm-unavailable" outcome: nothing is proposed, nothing is
; marked seen (so the job is reconsidered once the provider is configured), and
; the reason is in the result instead of in a stack trace.
(define (usable? v) (and (not (null? v)) (list? v)))

(define (consider profile job)
  (if (already-seen? job)
      (list (list "job" job) (list "outcome" "skipped-seen"))
      (let* ((scored (score-job profile job))
             (score  (if (usable? scored) (jget scored "score") 0)))
        (if (not (usable? scored))
            (list (list "job" job) (list "outcome" "llm-unavailable")
                  (list "note" "ctrl-llm returned no value — configure a provider"))
        (if (< score (job-agent-threshold))
            (begin (mark-seen! job "below-threshold")
                (list (list "job" job) (list "score" score)
                      (list "outcome" "below-threshold")))
            (let* ((bullets (tailor-bullets profile job))
                   (verdict (propose-application job scored bullets))
                   (action  (jget verdict "action")))
              (begin (mark-seen! job action)
                  (list (list "job" job) (list "score" score)
                        (list "bullets" bullets)
                        (list "outcome" action)))))))))

(define (run-job-agent url)
  (let* ((profile (job-agent-profile))
         (html    (fetch-page url))
         (jobs    (extract-jobs html)))
    (map (lambda (j) (consider profile j)) jobs)))

; ── running it on a list you already have ────────────────────────────────────
; run-job-agent needs a browser and an LLM to turn a URL into job records.
; run-jobs takes the records directly, so the half of the pipeline that is
; actually interesting — score, threshold, gate, propose, remember — runs with
; neither. This is the entry point for a proof of concept, and also the one a
; capture-by-click source would call once the human has done the authenticated
; read for you.
(define (run-jobs jobs)
  (let ((profile (job-agent-profile)))
    (map (lambda (j) (consider profile j)) jobs)))

; ── scheduled entry point ────────────────────────────────────────────────────
; A scheduled job's handler is called as (handler (list ) "") — the same shape
; as a route handler, so one function can serve both. See _execute_job in
; services/scheduler_service.py.
;
; SCHEDULED, NOT A CRON *AGENT*. cron_agents fires the LLM task loop with a
; prompt; scheduled_jobs calls an Omega symbol. This agent is code, not a
; prompt, so it belongs here — and it means the run is deterministic and needs
; no model just to decide to start.
;
; The source is sample-jobs until a browser and a provider are configured.
; That is deliberate and visible rather than hidden behind a stub that pretends
; to fetch: when fetch-page works, this one line changes.
(define (job-agent-cron params body)
  (run-jobs (sample-jobs)))

; Every weekday at 09:00. Nothing is applied by this — the run ends at a
; proposal in the cockpit, so the worst a bad schedule can do is queue work for
; a human to reject.
(define-cron "0 9 * * 1-5" job-agent-cron
  :name "job-agent"
  :description "Score new jobs, propose the ones worth applying to")

; A small realistic corpus: two strong matches, one weak, one that trips an
; avoid-term. Enough to show the threshold discriminating rather than just
; passing everything through.
(define (sample-jobs)
  (list
    (list (list "title" "Staff Engineer, Language & Runtime")
          (list "company" "Kernel Labs")
          (list "location" "Remote (US)")
          (list "url" "https://example.com/jobs/kernel-labs-staff")
          (list "summary" "Own our language design and runtime. Deep work on capability security, distributed systems and developer-tools. Lisp experience welcome."))
    (list (list "title" "Principal Systems Engineer")
          (list "company" "Reticule")
          (list "location" "Remote")
          (list "url" "https://example.com/jobs/reticule-principal")
          (list "summary" "Design distributed systems at scale. Python throughout. Strong interest in language design a plus."))
    (list (list "title" "Frontend Engineer II")
          (list "company" "Brightly")
          (list "location" "On-site, Austin")
          (list "url" "https://example.com/jobs/brightly-fe2")
          (list "summary" "React and CSS for our marketing site. Pixel-perfect work, fast iteration."))
    (list (list "title" "Senior Protocol Engineer")
          (list "company" "ChainForge")
          (list "location" "Remote")
          (list "url" "https://example.com/jobs/chainforge-protocol")
          (list "summary" "Build our crypto settlement layer. Distributed systems and Python. Adtech integrations a plus."))))

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
