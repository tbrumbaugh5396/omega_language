; html.ol — General-purpose Lisp → HTML library for Omega Lisp
;
; Self-contained: only requires the base interpreter (multiline_repl31.py).
; No dependency on types.ol, effects.ol, or std.ol.
;
; Usage:
;   (load "html.ol")
;   (html-save "page.html"
;     (page "My Site"
;       (h1 "Hello World")
;       (p "This is a paragraph.")
;       (ul (li "Item 1") (li "Item 2") (li "Item 3"))))
;
; Attribute syntax — keywords (symbols starting with :) become attributes:
;   (div :id "main" :class "container" "content")
;   => <div id="main" class="container">content</div>
;
; Void elements self-close:
;   (br) => <br>    (img :src "x.jpg" :alt "X") => <img src="x.jpg" alt="X">
;
; Full page with built-in stylesheet:
;   (html-save-page "out.html" "Title" (h1 "Hello") (p "World"))

;; ── PRIVATE HELPERS ──────────────────────────────────────────────────────

(define (_hc strs)
  (fold (lambda (a s) (string-append a s)) "" strs))

(define (_hv x)
  (cond
    ((null?   x) "")
    ((string? x) x)
    ((number? x) (number->string x))
    ((bool?   x) (if x "true" "false"))
    ((list?   x) (_hc (map _hv x)))
    (else        (number->string x))))

(define (_hs x)
  (if (number? x) (number->string x) (_hv x)))

(define (_hflatten lst)
  (cond
    ((null? lst) '())
    ((list? (first lst))
     (append (_hflatten (first lst)) (_hflatten (rest lst))))
    (else
     (cons (first lst) (_hflatten (rest lst))))))

(define (_hrange lo hi)
  (if (>= lo hi) '()
      (cons lo (_hrange (+ lo 1) hi))))

(define (_hmap-i f lst)
  (letrec ((go (lambda (i rem acc)
    (if (null? rem)
        (reverse acc)
        (go (+ i 1) (rest rem)
            (cons (f i (first rem)) acc))))))
  (go 0 lst '())))

;; ── ATTRIBUTE PARSING ────────────────────────────────────────────────────
;;
;; (div :id "main" :class "box" "hello") ->
;;   attrs:   ' id="main" class="box"'
;;   content: "hello"
;; Returns (list attr-string content-string).

(define (_hkw? s)
  (let ((str (cond ((symbol? s) (symbol->string s))
                   ((string? s) s)
                   (else ""))))
    (and (> (string-length str) 1)
         (equal? (substring str 0 1) ":"))))

(define (_hattr-name k)
  (let ((str (if (symbol? k) (symbol->string k) k)))
    (substring str 1 (string-length str))))

;; Escape attribute value: replace & and " only
(define (_hescape-attr v)
  (py-eval (string-append
    "(lambda s: s.replace('&','&amp;').replace('\"','&quot;'))('"
    v "')")))

;; Parse args -> (list attrs-string content-string)
(define _DQ (substring "\"x" 0 1))

(define (_hparse args)
  (letrec
    ((go (lambda (rem attrs content)
      (cond
        ((null? rem)
         (list (_hc attrs) (_hc content)))
        ((and (not (null? (rest rem))) (_hkw? (first rem)))
         (let ((aname (_hattr-name (first rem)))
               (aval  (_hescape-attr (_hs (second rem)))))
           (go (rest (rest rem))
               (append attrs (list " " aname "=" _DQ aval _DQ))
               content)))
        ((_hkw? (first rem))
         (go (rest rem)
             (append attrs (list " " (_hattr-name (first rem))))
             content))
        (else
         (go (rest rem) attrs
             (append content (list (_hv (first rem))))))))))
  (go args (list) (list))))


;; ── ELEMENT BUILDER ──────────────────────────────────────────────────────

(define _void-tags
  '(area base br col embed hr img input link meta param source track wbr))

(define (_hvoid? tag)
  (in (string->symbol tag) _void-tags))

(define (element tag . args)
  (let* ((parsed  (_hparse args))
         (attrs   (first  parsed))
         (content (second parsed)))
    (if (_hvoid? tag)
        (string-append "<" tag attrs ">")
        (string-append "<" tag attrs ">" content "</" tag ">"))))

;; ── ALL HTML5 TAGS ───────────────────────────────────────────────────────

(define (html    . a) (apply element (cons "html"    a)))
(define (head    . a) (apply element (cons "head"    a)))
(define (body    . a) (apply element (cons "body"    a)))
(define (main    . a) (apply element (cons "main"    a)))
(define (header  . a) (apply element (cons "header"  a)))
(define (footer  . a) (apply element (cons "footer"  a)))
(define (nav     . a) (apply element (cons "nav"     a)))
(define (aside   . a) (apply element (cons "aside"   a)))
(define (section . a) (apply element (cons "section" a)))
(define (article . a) (apply element (cons "article" a)))
(define (title   . a) (apply element (cons "title"   a)))
(define (meta    . a) (apply element (cons "meta"    a)))
(define (link    . a) (apply element (cons "link"    a)))
(define (script  . a) (apply element (cons "script"  a)))
(define (style   . a) (apply element (cons "style"   a)))
(define (h1 . a) (apply element (cons "h1" a)))
(define (h2 . a) (apply element (cons "h2" a)))
(define (h3 . a) (apply element (cons "h3" a)))
(define (h4 . a) (apply element (cons "h4" a)))
(define (h5 . a) (apply element (cons "h5" a)))
(define (h6 . a) (apply element (cons "h6" a)))
(define (p          . a) (apply element (cons "p"          a)))
(define (span       . a) (apply element (cons "span"       a)))
(define (div        . a) (apply element (cons "div"        a)))
(define (pre        . a) (apply element (cons "pre"        a)))
(define (code       . a) (apply element (cons "code"       a)))
(define (blockquote . a) (apply element (cons "blockquote" a)))
(define (strong . a) (apply element (cons "strong" a)))
(define (em     . a) (apply element (cons "em"     a)))
(define (b      . a) (apply element (cons "b"      a)))
(define (i      . a) (apply element (cons "i"      a)))
(define (u      . a) (apply element (cons "u"      a)))
(define (s      . a) (apply element (cons "s"      a)))
(define (small  . a) (apply element (cons "small"  a)))
(define (mark   . a) (apply element (cons "mark"   a)))
(define (abbr   . a) (apply element (cons "abbr"   a)))
(define (sub    . a) (apply element (cons "sub"    a)))
(define (sup    . a) (apply element (cons "sup"    a)))
(define (ul . a) (apply element (cons "ul" a)))
(define (ol . a) (apply element (cons "ol" a)))
(define (li . a) (apply element (cons "li" a)))
(define (dl . a) (apply element (cons "dl" a)))
(define (dt . a) (apply element (cons "dt" a)))
(define (dd . a) (apply element (cons "dd" a)))
(define (table      . a) (apply element (cons "table"      a)))
(define (thead      . a) (apply element (cons "thead"      a)))
(define (tbody      . a) (apply element (cons "tbody"      a)))
(define (tfoot      . a) (apply element (cons "tfoot"      a)))
(define (tr         . a) (apply element (cons "tr"         a)))
(define (th         . a) (apply element (cons "th"         a)))
(define (td         . a) (apply element (cons "td"         a)))
(define (caption    . a) (apply element (cons "caption"    a)))
(define (img        . a) (apply element (cons "img"        a)))
(define (figure     . a) (apply element (cons "figure"     a)))
(define (figcaption . a) (apply element (cons "figcaption" a)))
(define (video      . a) (apply element (cons "video"      a)))
(define (audio      . a) (apply element (cons "audio"      a)))
(define (source     . a) (apply element (cons "source"     a)))
(define (canvas     . a) (apply element (cons "canvas"     a)))
(define (iframe     . a) (apply element (cons "iframe"     a)))
(define (form     . a) (apply element (cons "form"     a)))
(define (input    . a) (apply element (cons "input"    a)))
(define (button   . a) (apply element (cons "button"   a)))
(define (label    . a) (apply element (cons "label"    a)))
(define (select   . a) (apply element (cons "select"   a)))
(define (option   . a) (apply element (cons "option"   a)))
(define (textarea . a) (apply element (cons "textarea" a)))
(define (fieldset . a) (apply element (cons "fieldset" a)))
(define (legend   . a) (apply element (cons "legend"   a)))
(define (a   . a) (apply element (cons "a"   a)))
(define (hr  . a) (apply element (cons "hr"  a)))
(define (br  . a) (apply element (cons "br"  a)))
(define (details . a) (apply element (cons "details" a)))
(define (summary . a) (apply element (cons "summary" a)))
(define (dialog  . a) (apply element (cons "dialog"  a)))

;; ── CLASS HELPERS ────────────────────────────────────────────────────────
;; (div/c "card active" :id "x" "content")
;; = (div :class "card active" :id "x" "content")

(define (div/c     cls . a) (apply element (cons "div"     (cons ":class" (cons cls a)))))
(define (span/c    cls . a) (apply element (cons "span"    (cons ":class" (cons cls a)))))
(define (p/c       cls . a) (apply element (cons "p"       (cons ":class" (cons cls a)))))
(define (section/c cls . a) (apply element (cons "section" (cons ":class" (cons cls a)))))
(define (article/c cls . a) (apply element (cons "article" (cons ":class" (cons cls a)))))
(define (header/c  cls . a) (apply element (cons "header"  (cons ":class" (cons cls a)))))
(define (nav/c     cls . a) (apply element (cons "nav"     (cons ":class" (cons cls a)))))
(define (footer/c  cls . a) (apply element (cons "footer"  (cons ":class" (cons cls a)))))
(define (ul/c      cls . a) (apply element (cons "ul"      (cons ":class" (cons cls a)))))
(define (ol/c      cls . a) (apply element (cons "ol"      (cons ":class" (cons cls a)))))
(define (li/c      cls . a) (apply element (cons "li"      (cons ":class" (cons cls a)))))
(define (button/c  cls . a) (apply element (cons "button"  (cons ":class" (cons cls a)))))

;; ── PAGE BUILDERS ────────────────────────────────────────────────────────

(define (page title-str . children)
  (string-append
    "<!DOCTYPE html>\n"
    (html :lang "en"
      (head
        (meta :charset "UTF-8")
        (meta :name "viewport" :content "width=device-width, initial-scale=1.0")
        (title title-str))
      (apply body children))))

(define (page-with-style title-str css-str . children)
  (string-append
    "<!DOCTYPE html>\n"
    (html :lang "en"
      (head
        (meta :charset "UTF-8")
        (meta :name "viewport" :content "width=device-width, initial-scale=1.0")
        (title title-str)
        (style css-str))
      (apply body children))))

(define (page-with-css title-str css-href . children)
  (string-append
    "<!DOCTYPE html>\n"
    (html :lang "en"
      (head
        (meta :charset "UTF-8")
        (meta :name "viewport" :content "width=device-width, initial-scale=1.0")
        (title title-str)
        (link :rel "stylesheet" :href css-href))
      (apply body children))))

;; ── LIST / TABLE BUILDERS ────────────────────────────────────────────────

(define (ul-of items)
  (apply ul (map (lambda (x) (li (_hv x))) items)))

(define (ol-of items)
  (apply ol (map (lambda (x) (li (_hv x))) items)))

(define (select-of name values)
  (apply select
    (cons ":name" (cons name
      (map (lambda (v) (option :value v v)) values)))))

(define (table-of headers rows)
  (table
    (thead (apply tr (map th headers)))
    (apply tbody
      (map (lambda (row)
             (apply tr (map (lambda (cell) (td (_hv cell))) row)))
           rows))))

(define (dl-of pairs)
  (apply dl
    (_hflatten
      (map (lambda (pair)
             (list (dt (_hv (first pair)))
                   (dd (_hv (second pair)))))
           pairs))))

;; ── COMPONENTS ───────────────────────────────────────────────────────────

(define (navbar links)
  (nav
    (apply ul
      (map (lambda (lnk) (li (a :href (second lnk) (first lnk))))
           links))))

(define (card title-str . content)
  (div/c "card"
    (div/c "card-header" (h3 title-str))
    (apply div/c (cons "card-body" content))))

(define (badge text)
  (span/c "badge" text))

(define (alert kind . content)
  (apply div/c (cons (string-append "alert alert-" kind) content)))

(define (breadcrumb items)
  (nav :aria-label "breadcrumb"
    (apply ol/c (cons "breadcrumb"
      (_hmap-i
        (lambda (i item)
          (if (= i (- (length items) 1))
              (li/c "breadcrumb-item active" item)
              (li/c "breadcrumb-item" (a :href "#" item))))
        items)))))

;; ── FRAGMENTS ────────────────────────────────────────────────────────────

(define (raw html-str) html-str)

(define (comment text)
  (string-append "<!-- " text " -->"))

(define (when-html condition html-str)
  (if condition html-str ""))

(define (render-list items fn)
  (_hc (map fn items)))

(define (join-html sep elements)
  (if (null? elements) ""
      (fold (lambda (acc el) (string-append acc sep el))
            (first elements)
            (rest elements))))

(define (repeat-html n thunk)
  (_hc (map (lambda (_) (thunk)) (_hrange 0 n))))

;; ── CSS-IN-LISP ──────────────────────────────────────────────────────────

(define (css-rule selector . props)
  (letrec ((pp (lambda (ps)
    (if (or (null? ps) (null? (rest ps))) ""
        (string-append (first ps) ": " (second ps) "; "
                       (pp (rest (rest ps))))))))
  (string-append selector " { " (pp props) "}\n")))

(define (css-block rules)
  (_hc rules))

(define (css-media query . rules)
  (string-append "@media (" query ") {\n" (_hc rules) "}\n"))

(define (css-vars pairs)
  (string-append ":root {\n"
    (_hc (map (lambda (p)
                (string-append "  --" (first p) ": " (second p) ";\n"))
              pairs))
    "}\n"))

(define (css-keyframes name . steps)
  (string-append "@keyframes " name " {\n"
    (_hc (map (lambda (step)
                (string-append "  " (first step) " { "
                  (_hc (map (lambda (p)
                               (string-append (first p) ": " (second p) "; "))
                            (rest step)))
                  "}\n"))
              steps))
    "}\n"))

;; ── BUILT-IN STYLESHEETS ─────────────────────────────────────────────────

(define css-reset
  (css-block (list
    (css-rule "*, *::before, *::after"
      "box-sizing" "border-box" "margin" "0" "padding" "0")
    (css-rule "body"
      "font-family" "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
      "font-size" "16px" "line-height" "1.6" "color" "#333")
    (css-rule "img"     "max-width" "100%" "height" "auto")
    (css-rule "a"       "color" "#0070f3" "text-decoration" "none")
    (css-rule "a:hover" "text-decoration" "underline"))))

(define css-utilities
  (css-block (list
    (css-rule ".container"      "max-width" "1100px" "margin" "0 auto" "padding" "0 20px")
    (css-rule ".flex"           "display" "flex")
    (css-rule ".flex-col"       "flex-direction" "column")
    (css-rule ".flex-wrap"      "flex-wrap" "wrap")
    (css-rule ".items-center"   "align-items" "center")
    (css-rule ".justify-center" "justify-content" "center")
    (css-rule ".gap-sm"         "gap" "8px")
    (css-rule ".gap-md"         "gap" "16px")
    (css-rule ".gap-lg"         "gap" "24px")
    (css-rule ".p-sm"           "padding" "8px")
    (css-rule ".p-md"           "padding" "16px")
    (css-rule ".p-lg"           "padding" "24px")
    (css-rule ".m-auto"         "margin" "auto")
    (css-rule ".text-sm"        "font-size" "0.875rem")
    (css-rule ".text-lg"        "font-size" "1.25rem")
    (css-rule ".text-xl"        "font-size" "1.5rem")
    (css-rule ".text-center"    "text-align" "center")
    (css-rule ".text-muted"     "color" "#666")
    (css-rule ".rounded"        "border-radius" "4px")
    (css-rule ".rounded-lg"     "border-radius" "12px")
    (css-rule ".shadow"         "box-shadow" "0 2px 8px rgba(0,0,0,0.1)")
    (css-rule ".shadow-lg"      "box-shadow" "0 8px 32px rgba(0,0,0,0.15)")
    (css-rule ".bg-white"       "background" "white")
    (css-rule ".bg-light"       "background" "#f8f9fa")
    (css-rule ".border"         "border" "1px solid #dee2e6")
    (css-rule ".w-full"         "width" "100%")
    (css-rule ".hidden"         "display" "none"))))

(define css-card
  (css-block (list
    (css-rule ".card"
      "background" "white" "border-radius" "8px"
      "box-shadow" "0 2px 8px rgba(0,0,0,0.1)"
      "overflow" "hidden" "margin-bottom" "16px")
    (css-rule ".card-header"
      "padding" "12px 20px" "border-bottom" "1px solid #eee" "font-weight" "600")
    (css-rule ".card-body"   "padding" "20px")
    (css-rule ".card-footer"
      "padding" "12px 20px" "border-top" "1px solid #eee"
      "color" "#666" "font-size" "0.875rem"))))

(define css-badge
  (css-block (list
    (css-rule ".badge"
      "display" "inline-block" "padding" "2px 8px" "border-radius" "999px"
      "font-size" "0.75rem" "font-weight" "600"
      "background" "#0070f3" "color" "white"))))

(define css-alert
  (css-block (list
    (css-rule ".alert"
      "padding" "12px 16px" "border-radius" "4px"
      "border-left" "4px solid currentColor" "margin" "16px 0")
    (css-rule ".alert-info"    "background" "#e8f4fd" "color" "#0c5460")
    (css-rule ".alert-success" "background" "#d4edda" "color" "#155724")
    (css-rule ".alert-warning" "background" "#fff3cd" "color" "#856404")
    (css-rule ".alert-danger"  "background" "#f8d7da" "color" "#721c24"))))

(define css-default
  (string-append css-reset css-utilities css-card css-badge css-alert))

;; ── FILE OUTPUT ──────────────────────────────────────────────────────────

(define (html-save filename html-str)
  (write-file filename html-str)
  filename)

(define (html-save-page filename title-str . children)
  (html-save filename
    (page-with-style title-str css-default
      (apply main (cons ":class" (cons "container" children))))))
