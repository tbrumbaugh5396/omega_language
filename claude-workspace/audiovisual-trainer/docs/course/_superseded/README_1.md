# The Mathematics Behind Graphics

A self-directed course, from photons to fragment shaders.

## The thesis

Almost everything in this domain is one of two things:

1. **An integral of a signal against a basis.** Cone response, CIE tristimulus values, pixel filtering, texture minification, the rendering equation — all the same shape: $\int f(x)\,g(x)\,dx$.
2. **A change of basis.** sRGB to XYZ, XYZ to LMS, world space to clip space, spatial domain to frequency domain.

If a module ever feels like arbitrary trivia, ask which of the two it is. It is always one of them.

## Module order

| # | Module | Core math | Why it's here |
|---|--------|-----------|---------------|
| 0 | [Radiometry](00-radiometry.md) | Solid angles, hemisphere integrals | Defines what light *is* as a quantity |
| 1 | [The Eye](01-the-eye.md) | Inner products, null spaces, linear maps | Explains why 3 numbers suffice |
| 2 | [Colorimetry](02-colorimetry.md) | Change of basis, projective geometry, convex hulls | Builds the coordinate systems |
| 3 | [Additive & Subtractive](03-additive-subtractive.md) | Vector spaces vs. multiplicative algebras | Explains why your blends look wrong |
| 4 | [Color Organization](04-color-organization.md) | Cylindrical coordinates, perceptual metrics | Turns color into something navigable |
| 5 | [Display](05-display.md) | Sampling theory, quantization, transfer functions | Continuous math meets a finite grid |
| 6 | [The GPU Pipeline](06-gpu-pipeline.md) | Homogeneous coordinates, barycentrics, SIMD | How triangles become fragments |
| 7 | [Shaders](07-shaders.md) | Implicit surfaces, noise, filter widths | Book of Shaders, now grounded |

## Reading the difficulty curve

The "elementary" modules (1–2, color) are mathematically heavier than the "advanced" ones (7, shaders). This is normal and not a sign you've sequenced things badly. Colorimetry requires you to think about infinite-dimensional function spaces; SDF raymarching requires you to think about distance. Expect to spend more calendar time on modules 1–2 than on 6–7.

## Prerequisites, honestly

- **Linear algebra**: matrix–vector products, change of basis, null space, rank. Non-negotiable — it *is* the subject.
- **Calculus**: definite integrals, partial derivatives. You'll integrate over wavelength and over the hemisphere.
- **Nice to have**: a little Fourier analysis for module 5. You can pick it up there.
- **Code**: any language with array math for the CPU work; GLSL ES 3.0 or WebGL2 for the shader work.

## Build order for the code

Each artifact is small. Each one makes an abstraction concrete.

1. **Spectral integrator** — load CIE tables, integrate an SPD to XYZ. (Module 1–2)
2. **Chromaticity diagram renderer** — plot the spectral locus, draw gamut triangles. (Module 2)
3. **Your own color conversions in GLSL** — sRGB ↔ linear ↔ XYZ ↔ Oklab, derived not pasted. (Module 2–4)
4. **Three-way gradient comparison** — the same interpolation in sRGB-encoded, linear, and Oklab. (Module 3)
5. **Banding and dither demo** — quantize an 8-bit ramp, add ordered and blue-noise dither. (Module 5)
6. **Software rasterizer** — CPU, ~200 lines, edge functions and perspective-correct barycentrics. (Module 6)
7. **SDF scene with analytic antialiasing** — where `fwidth` finally makes sense. (Module 7)

The software rasterizer is the highest-value item on this list. Writing one teaches you more about the GPU than any amount of API tutorial.

## A note on external data

Modules 1–2 need the CIE tables (colour matching functions, D65 illuminant SPD, cone fundamentals). These are published by the CIE and mirrored by the Colour Science project and by CVRL (Colour & Vision Research Laboratory). Grab them once at 5 nm resolution and keep them in a `data/` folder — several modules depend on them.
