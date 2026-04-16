;; Example: Freeze the current state of the math-engine
(define math-image (freeze-env "math-engine-v1"))

;; This 'math-image' can now be saved to disk as a JSON/Binary file
(save-image "math-engine-v1.img" math-image)