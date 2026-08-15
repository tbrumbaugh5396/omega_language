# Module 5 — Display: Continuous Math Meets a Finite Grid

**Goal:** understand a pixel as a *sample*, not a square; understand aliasing as spectral overlap; and understand gamma, HDR, and dithering as three answers to the same quantization problem.

---

## 5.1 A pixel is not a little square

This is the most consequential misconception in graphics, and Alvy Ray Smith wrote a memo with that title in 1995 for good reason.

An image is a **continuous 2D signal** $f(x,y)$. The framebuffer stores **point samples** of it on a lattice. The display then **reconstructs** a continuous signal from those samples by convolving with a reconstruction filter — which for an LCD is roughly a box the shape of the subpixel aperture, but that's a property of the *display hardware*, not of the sample.

Once you hold this, three things unify:

- **Antialiasing** = low-pass filtering before sampling.
- **Texture filtering** = reconstruction plus prefiltering.
- **Resolution** = sampling rate.

---

## 5.2 Sampling theory, the minimum you need

Sampling at interval $T$ multiplies the signal by a Dirac comb. In the frequency domain, multiplication becomes **convolution**, and convolving with a comb **replicates the spectrum** at every multiple of the sampling frequency $f_s = 1/T$.

$$\hat{f}_{sampled}(\xi) = \sum_{n=-\infty}^{\infty} \hat{f}(\xi - n f_s)$$

If the signal contains frequencies above $f_s/2$ — the **Nyquist limit** — the copies overlap. Overlapping is irreversible: high frequencies fold down and masquerade as low ones.

$$\boxed{\text{Aliasing is spectral overlap. It cannot be fixed after sampling.}}$$

**Nyquist–Shannon:** a signal band-limited to below $f_s/2$ can be perfectly reconstructed from its samples, via convolution with $\operatorname{sinc}(x) = \sin(\pi x)/(\pi x)$.

Sinc is the ideal reconstruction filter and it is unusable: infinite support, negative lobes (ringing / Gibbs). Practical filters trade off:

| Filter | Support | Character |
|---|---|---|
| Box | 1 | Blocky; poor stopband; cheap |
| Tent (bilinear) | 2 | Soft; what GPU bilinear does |
| Cubic (Mitchell–Netravali) | 4 | Tunable blur/ring via $(B,C)$; $(1/3,1/3)$ is the good default |
| Lanczos ($a$=2,3) | 4–6 | Sharp; visible ringing on hard edges |
| Gaussian | ∞ (truncated) | No ringing; always somewhat soft |

### Where this bites in graphics

**Geometric edges are not band-limited.** A triangle edge is a step function; its spectrum decays as $1/\xi$ and never terminates. **No sample count eliminates edge aliasing** — you can only push it down. This is why MSAA (sample coverage at higher rate, shade once) exists, and why analytic coverage (Module 7) is better when you can compute it.

**Texture minification** is the classic case: a texture sampled at less than one texel per pixel aliases into shimmer. **Mipmapping** prefilters — each level is a low-passed, downsampled copy — so you can pick a level whose Nyquist limit matches the screen-space sampling rate. Trilinear blends between levels to hide the switch; anisotropic filtering handles the case where the footprint is elongated (a floor viewed at a grazing angle), where a single isotropic mip level is either too blurry in one axis or aliased in the other.

**Rotating a checkerboard** or panning a fine-striped texture produces moiré — that's the folded frequencies moving.

**And note the interaction with Module 3:** mip generation must average in **linear light**. Averaging encoded values darkens. Both errors compound.

---

## 5.3 The physical display

**Resolution and PPI.** $\text{PPI} = \sqrt{w^2 + h^2}/\text{diagonal inches}$.

**Angular resolution is what matters.** Human foveal acuity resolves roughly **1 arcminute** (≈30 cycles/degree for high-contrast gratings; vernier acuity is far finer, ~5 arcseconds, which is why we see subpixel jaggies at all). Pixels per degree:

$$\text{PPD} = \frac{\text{PPI} \cdot d \cdot \pi}{180}, \quad d \text{ in inches}$$

At ~60 PPD you're at the limit for detail. A 27" 4K monitor at 24" viewing gives roughly 100 PPD — comfortably past. A phone at 12" with 460 PPI gives ~96. "Retina" claims are just this arithmetic.

**Subpixel structure.** LCD pixels are typically three vertical RGB stripes. **Subpixel rendering** (ClearType, FreeType LCD filtering) treats them as three independent luminance samples, tripling horizontal resolution for text. The costs: it depends on subpixel order (fails on rotated screens, fails on PenTile OLED layouts), and it introduces color fringing that must be filtered. It's fallen out of favor as PPI rose and as compositors moved to arbitrary rotation and scaling.

**Panel technologies**, briefly, for what they imply about your math:

- **LCD/IPS** — backlight + liquid crystal shutters. Never truly black (backlight leaks). Good color, limited contrast (~1000:1).
- **VA** — better native contrast (~3000:1), slower transitions.
- **OLED** — per-pixel emission, true black, effectively infinite contrast ratio. Limited full-screen sustained brightness (ABL — automatic brightness limiting), so peak-vs-sustained nits differ a lot.
- **Mini-LED / FALD** — LCD with zoned backlight. Contrast improves; **blooming** appears around bright objects on dark fields because the zone is larger than the object.
- **Quantum dot** — narrow-band emitters, wider gamut. Narrower primaries = bigger triangle in Module 2's diagram.

**Refresh, latency, persistence.** Refresh rate is temporal sampling — the same Nyquist argument applies in time, and temporal aliasing is why wagon wheels spin backwards. **Persistence** (how long a frame is displayed) causes motion blur on sample-and-hold displays independent of refresh rate; black-frame insertion and backlight strobing reduce it at the cost of brightness. Variable refresh (FreeSync/G-Sync) removes the mismatch between render cadence and scanout that causes tearing or judder.

---

## 5.4 Transfer functions

An **EOTF** (electro-optical transfer function) maps stored code values → emitted light. Its inverse-ish partner, the **OETF**, maps scene light → code values. The **OOTF** is the end-to-end rendering intent that relates them (and is deliberately not identity — displays are viewed in dimmer surrounds than the original scene, so a slight contrast boost is baked in).

### sRGB

Encoding (linear → code):

$$V = \begin{cases}
12.92\,L & L \le 0.0031308 \\
1.055\,L^{1/2.4} - 0.055 & \text{otherwise}
\end{cases}$$

Decoding (code → linear):

$$L = \begin{cases}
V/12.92 & V \le 0.04045 \\
\left(\frac{V+0.055}{1.055}\right)^{2.4} & \text{otherwise}
\end{cases}$$

The exponent is 2.4 but the **effective overall gamma is ≈2.2** because of the linear toe. The toe exists to bound the derivative at zero — a pure power function has infinite slope there, which amplifies noise and quantization in the darkest codes.

**The reason gamma exists is Module 1.7,** not CRTs. The eye's response is roughly a power law with exponent ~1/3 to 1/2; encoding with a matching curve equalizes perceptual quantization error. The CRT's coincidental $\approx2.2$ response is a historical accident that made the scheme free to implement.

**Count the codes.** With 8 bits linear, the step from 0 to 1/255 is a 100% relative change — grossly visible. The step from 254 to 255 is 0.4% — wasted. Gamma encoding redistributes so each step is roughly a constant *ratio*, which is what Weber's law asks for.

### HDR: PQ and HLG

**PQ (SMPTE ST 2084, "Perceptual Quantizer")** is defined in **absolute nits**, 0–10,000, and derived from the Barten contrast sensitivity model — the curve is designed so that one code step is always just below the threshold of visibility.

$$\text{PQ}(L) = \left(\frac{c_1 + c_2 Y^{m_1}}{1 + c_3 Y^{m_1}}\right)^{m_2}, \quad Y = L/10000$$

with $m_1 = 2610/16384$, $m_2 = 2523/4096 \cdot 128$, $c_1 = 3424/4096$, $c_2 = 2413/4096\cdot32$, $c_3=2392/4096\cdot32$.

Absolute encoding means the same code should produce the same nits everywhere — which is why PQ content needs **display-referred tone mapping** when the actual display can't reach the mastering peak, and why HDR grading is harder than SDR.

**HLG (Hybrid Log-Gamma)** is relative and backward-compatible: a square-root curve in the lower range (matching legacy gamma) transitioning to logarithmic above. Designed for broadcast, where you can't control the display.

---

## 5.5 Quantization, banding, and dither

Quantization is rounding. Rounding error, when the signal varies slowly, is **correlated with the signal** — and correlated error is visible as structure. That structure is **banding**: the Mach-band-amplified contours across a smooth gradient.

The fix is **dither**: add noise *before* quantizing, converting correlated error into uncorrelated error. Uncorrelated error is noise, and the visual system is far more tolerant of noise than of structure. You are trading a visible artifact for an invisible one.

### Ordered / Bayer

A recursive threshold matrix:

$$M_1 = \begin{bmatrix}0&2\\3&1\end{bmatrix}, \qquad
M_{n+1} = \begin{bmatrix}4M_n & 4M_n+2\\ 4M_n+3 & 4M_n+1\end{bmatrix}$$

Normalize to $[0,1)$, add, quantize. Cheap, tileable, deterministic — but it has strong periodic structure, so it produces a visible crosshatch. Fine for retro aesthetics, poor for hiding.

### Blue noise

Noise whose power spectrum is concentrated at **high** spatial frequencies, with little low-frequency energy. Because the eye's contrast sensitivity falls off at high frequencies, blue noise is the least visible noise of a given amplitude. This makes it the right dither for almost everything, and also the right sample distribution for stochastic rendering (shadow sampling, SSAO, path tracing) — the error it produces is high-frequency and easy for a denoiser or the eye to reject.

Generate offline (void-and-cluster, or Ulichney's method), store as a small tiling texture, sample per-fragment:

```glsl
// 1 LSB of triangular blue noise before quantization
float bn = texture(blueNoiseTex, gl_FragCoord.xy / 64.0).r;
float t  = (bn + texture(blueNoiseTex, gl_FragCoord.xy/64.0 + 0.5).r) - 1.0; // TPDF
color += t / 255.0;
```

**Triangular PDF** (sum of two uniforms) rather than uniform: TPDF dither makes the quantization error's *variance* independent of the signal, which removes noise modulation. This is standard practice in audio and applies identically here.

### Error diffusion

Floyd–Steinberg propagates the quantization error to unprocessed neighbors (7/16 right, 3/16 down-left, 5/16 down, 1/16 down-right). Excellent quality, inherently serial, so it's a CPU/offline technique. Worth implementing once to see how good 1-bit output can look.

**In practice:** any modern renderer computes in float16 or float32 and dithers by ~1 LSB on output to 8-bit. It costs nothing and eliminates banding in skies, gradients, and fog. Do it.

---

## 5.6 Tone mapping and gamut mapping

Scene radiance is unbounded ($10^{-3}$ to $10^{9}$ nits). Displays are bounded. **Tone mapping** is the compression, and it is fundamentally an *aesthetic* problem constrained by perception, not a solved math problem.

**Reinhard** — $L_d = L/(1+L)$, or the extended form with a white point. Simple, desaturates highlights, no shoulder character. Good for learning, dull in production.

**Filmic / Hable (Uncharted 2)** — an explicit toe + linear + shoulder curve. The toe crushes blacks slightly (which reads as "contrast"), the shoulder rolls off highlights gracefully.

**ACES** — a full color management *system*, not just a curve: wide-gamut scene-referred working space (AP0/AP1), a Reference Rendering Transform, and per-display Output Transforms. The RRT+ODT together produce the filmic look. The widely-copied "ACES fitted" GLSL snippet is an approximation of the sRGB ODT, not ACES itself. It has a known problem: strong hue shifts on saturated bright colors (notably the "fire turns yellow" effect).

**AgX** — recent, designed specifically to fix that. It desaturates toward white as values approach the display peak, which is what film does chemically and what the eye expects. Notably better on saturated emissives. Now Blender's default.

**Critical:** tone mapping is a **per-color-triple** operation applied at the very end, on linear-light HDR values, before the OETF. Applying it per-channel independently causes hue shifts; applying it to luminance only and rescaling chroma preserves hue but can clip. Every tone mapper picks a compromise here, and that compromise *is* its aesthetic signature.

**Gamut mapping** is the chromatic sibling: a color outside the display triangle must be moved inside. Options, from bad to good — per-channel clip (shifts hue), clip in LCh at constant $L$ and $h$ reducing $C$ (preserves hue, the sane default), or a soft compression that also moves in-gamut colors slightly to preserve gradient continuity. Your Exercise 2.6 already covered this ground.

---

## Exercises

**5.1** **Aliasing from scratch.** Sample $\sin(2\pi f x)$ at fixed rate for $f$ sweeping past Nyquist. Plot the sampled sequence's apparent frequency vs. $f$ and observe the fold. Then do it in 2D with a radial zone plate $\sin(k(x^2+y^2))$ — the moiré rings are the most instructive image in this module.

**5.2** Implement box, tent, Mitchell $(1/3,1/3)$, and Lanczos-3 resampling. Downscale a detailed image 4× with each. Compare sharpness and ringing. Then compare correct (linear-light) vs naive (encoded) resampling with the same filter.

**5.3** Build a mip chain manually and implement trilinear sampling in a shader. Render an infinite checkerboard plane. Toggle between: no mips (shimmer), mips with nearest level (visible transitions), trilinear, and trilinear with an anisotropic tweak. Watch the horizon.

**5.4** Implement the exact sRGB EOTF and its inverse. Verify round-trip through 8-bit quantization: how many of the 256 codes survive a round trip exactly? Repeat with `pow(2.2)` and count the failures.

**5.5** **Banding lab.** Render a very dark gradient (linear 0.0 → 0.02) to 8-bit. Then apply: no dither, uniform white noise, TPDF white noise, Bayer 8×8, blue noise TPDF. Zoom in. Rank them. This is the single most immediately useful technique in this module.

**5.6** Implement Bayer matrix generation recursively for $2^n$. Implement void-and-cluster blue noise generation (or load a precomputed tile). Compare their power spectra via FFT — you should see the low-frequency hole in the blue noise.

**5.7** Implement Reinhard, Hable, the ACES approximation, and AgX in one shader with a toggle. Feed it an HDR image (or a synthetic scene with a 10,000:1 range). Compare highlight rolloff, and specifically compare behavior on a saturated bright orange emissive.

**5.8** Implement PQ encode/decode. Take an HDR image and render it two ways: PQ-encoded assuming a 1000-nit display, and again assuming 4000. Note that the same code values imply different appearance — this is the absolute-encoding problem.

---

## Checkpoint

- Why can't you fix aliasing with a post-process blur?
- Why is edge aliasing impossible to eliminate with more samples?
- Why does gamma encoding exist, in terms of Weber's law?
- Why is blue noise better than white noise for dithering?
- Why does the same PQ code value not guarantee the same appearance?

← [Module 4: Color Organization](04-color-organization.md) | → [Module 6: The GPU Pipeline](06-gpu-pipeline.md)
