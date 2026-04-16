(module Std
  (export math list str test core net gui)
          
  (import "math.ol"     Math)
  (import "string.ol"   String)
  (import "list.ol"     List)
  (import "test.ol"     Test)
  (import "core.ol"     Core)
  (import "net.ol"      Net)
  (import "ui_react.ol" GUI) ; Using the reactive version for the "Standard" GUI

  ; Assign sub-modules to fields
  (define math Math)
  (define list List)
  (define str  String)
  (define test Test)
  (define core Core)
  (define net  Net)
  (define gui  GUI)
)