;; modules/std.ol — Standard Library for Omega Lisp
;;
;; Loads the type and effect systems and adds common utilities.
;; Designed to be the single import for application code.
;;
;; Usage:  (load "std.ol")
;;         (import "std.ol" std)

;; (load "modules/types.ol")
;; (load "modules/effects.ol")

(module Std
  (export core continuations effects list alist functions types predicate monad math random time str test net gui json html io)

  (import "modules/core.ol"             Core) 
  (import "modules/continuations.ol"    Continuations)
  (import "modules/effects.ol"          Effects)
  (import "modules/list.ol"             List) 
  (import "modules/alist.ol"            Alist)
  (import "modules/functions.ol"        Functions)   
  (import "modules/types.ol"            Types)  
  (import "modules/predicate.ol"        Predicate)  
  (import "modules/monad.ol"            Monad)  
  (import "modules/math.ol"             Math)
  (import "modules/random.ol"           Random)
  (import "modules/time.ol"             Time)  
  (import "modules/string.ol"           String)
  (import "modules/debug.ol"            Debug)
  (import "modules/test.ol"             Test)
  (import "modules/network.ol"          Network)
  (import "modules/ui_react.ol"         GUI)          ; Using the reactive version for the "Standard" GUI
  (import "modules/ui.ol"               UI)
  (import "modules/json.ol"             JSON)
  (import "modules/html.ol"             HTML)
  (import "modules/input_and_output.ol" IO)

  ; Assign sub-modules to fields
  (define core Core)
  (define continuations Continuations)
  (define effects Effects)
  (define list List)
  (define alist Alist)
  (define functions Functions)
  (define types Types)
  (define predicate Predicate)
  (define monad Monad)
  (define math Math)
  (define random Random)
  (define time Time)
  (define str  String)
  (define test Test)
  (define network  Network)
  (define gui  GUI)
  (define ui UI)
  (define json JSON)
  (define html HTML)
  (define io IO)
)