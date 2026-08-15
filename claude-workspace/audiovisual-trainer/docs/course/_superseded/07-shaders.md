# Module 7 — Shaders: Book of Shaders, Grounded

**Goal:** re-derive the standard shader toolkit from the mathematics of the previous seven modules, so that `smoothstep` and `fwidth` stop being incantations. Then close the loop with the rendering equation.

---

## 7.1 The fragment shader is a function

$$\text{color} = f(\mathbf{p}), \qquad \mathbf{p} \in \mathbb{R}^2$$

Pure, stateless, evaluated in parallel at every sample point. No loops over pixels, no knowledge of neighbors except through derivatives. Everything in this module is about constructing interesting $f$.

Normalize coordinates first, and preserve aspect ratio, or every circle you draw will be an ellipse:

```glsl
vec2 uv = (2.0 * gl_FragCoord.xy - u_resolution) / u_resolution.y;
// now: origin at center, y in [-1,1], x scaled by aspect
```

---

## 7.2 Interpolation and smoothstep

`step(edge, x)` is the Heaviside function — a discontinuity, therefore infinite bandwidth, therefore (Module 5.2) guaranteed to alias. Never ship a bare `step` on a spatially varying quantity.

`smoothstep(e0, e1, x)` clamps $t = (x-e_0)/(e_1-e_0)$ then applies:

$$S(t) = 3t^2 - 2t^3$$

This is the unique cubic Hermite polynomial satisfying $S(0)=0$, $S(1)=1$, $S'(0)=S'(1)=0$. **The zero endpoint derivatives are the point** — they make it $C^1$ continuous, so no visible crease where the interpolation begins and ends. `step` is $C^{-1}$; linear is $C^0$ (visible kinks — Mach banding will find them); smoothstep is $C^1$.

Perlin's **quintic** goes further:

$$S_5(t) = 6t^5 - 15t^4 + 10t^3$$

with $S_5''(0) = S_5''(1) = 0$ as well, so it's $C^2$. This matters for gradient noise: the *derivative* of the noise field is used for normals and for analytic differentiation, and a discontinuous second derivative shows up as visible creases along the lattice grid lines. Perlin's original 1985 noise used the cubic and had exactly that artifact; he switched to the quintic in 2002.

---

## 7.3 Signed distance fields

$$d(\mathbf{p}) = \begin{cases} -\text{dist to boundary} & \text{inside} \\ +\text{dist to boundary} & \text{outside}\end{cases}$$

The key property: $|\nabla d| = 1$ everywhere (it satisfies the eikonal equation). That unit gradient is what makes everything downstream work — raymarching step sizes, outline widths, and antialiasing all rely on "one unit of $d$ = one unit of space."

**Primitives:**

```glsl
float sdCircle(vec2 p, float r) { return length(p) - r; }

float sdBox(vec2 p, vec2 b) {
    vec2 d = abs(p) - b;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
    //     ^ exterior distance      ^ interior (negative)
}

float sdSegment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}
```

**Combination — a Boolean algebra:**

```glsl
float opUnion(float a, float b)     { return min(a, b); }
float opIntersect(float a, float b) { return max(a, b); }
float opSubtract(float a, float b)  { return max(a, -b); }   // a minus b
```

`min` and `max` give **exact** distances outside the union but only bounds inside; that's usually fine.

**Smooth union** (polynomial, from Inigo Quilez) — the operation that makes SDFs feel organic:

```glsl
float opSmoothUnion(float a, float b, float k) {
    float h = clamp(0.5 + 0.5*(b-a)/k, 0.0, 1.0);
    return mix(b, a, h) - k*h*(1.0-h);
}
```

Note the `mix` weighted by a clamped linear ramp, minus a quadratic correction — it's a blend between the two fields plus a term that pulls the seam inward, producing a fillet of radius ~$k$.

**Transformations act on the input, inverted:**

```glsl
p = p - offset;              // translate
p = rot(-angle) * p;         // rotate
p = mod(p + 0.5*c, c) - 0.5*c;  // INFINITE repetition, free
```

Domain repetition costing nothing is a genuinely remarkable property. You are not instancing geometry; you are folding space.

**Caveat:** non-uniform scaling breaks the metric. If you scale $p$ by $s$ before evaluating, multiply the result by $\min(s)$ to keep a conservative (Lipschitz-1) bound, or your raymarcher will overshoot.

**Derived effects, all one-liners because $|\nabla d|=1$:**

```glsl
float outline = abs(d) - thickness;   // shell
float ring    = abs(d - r) - t;       // concentric ring
float rounded = d - r;                // rounds any shape's corners by r
```

---

## 7.4 Analytic antialiasing — where Modules 5 and 6 pay off

Recall from Module 5: the correct thing to do is integrate the signal over the pixel footprint before sampling. For an SDF you can approximate that integral in closed form, because you know exactly how far the pixel center is from the edge and how fast $d$ changes.

```glsl
float w = fwidth(d);                          // ≈ |d| change per pixel
float alpha = smoothstep(w, -w, d);           // 1 inside, 0 outside, ramp of ~2px
```

Read it as a sentence: `fwidth` (Module 6.6) gives the screen-space filter width; `smoothstep` gives a smooth transition of exactly that width; therefore the coverage estimate is correct at any zoom level, in perspective, on a curved surface, everywhere. **This is prefiltering, not blurring.** It is not "adding a soft edge" — it is evaluating the pixel's coverage integral.

Compare: `step(0.0, d)` aliases. A fixed `smoothstep(-0.01, 0.01, d)` is correct at exactly one zoom level and wrong everywhere else. The `fwidth` version is correct always.

**And it composes with Module 3:** `alpha` is coverage, so blend in linear light, or your antialiased edges will have the wrong average luminance — which is precisely the "thin white text looks too thin, thin black text looks too fat" problem.

**Caveat:** `fwidth` is undefined in divergent control flow (Module 6.6). Compute it before you branch.

---

## 7.5 Noise

The hash is the foundation. It must be deterministic, fast, and free of visible structure. This one is widely used and adequate:

```glsl
float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
```

Be aware: `sin`-based hashes vary between GPUs and break down at large coordinates. For anything you ship, use integer bit-mixing (PCG, xxhash) in a shader stage that supports integers.

**Value noise** — random value per lattice point, interpolate:

```glsl
float valueNoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f*f*(3.0-2.0*f);                  // smoothstep
    return mix(mix(hash21(i+vec2(0,0)), hash21(i+vec2(1,0)), u.x),
               mix(hash21(i+vec2(0,1)), hash21(i+vec2(1,1)), u.x), u.y);
}
```

Cheap, but blobby, with visible axis-aligned lattice structure.

**Gradient (Perlin) noise** — random *gradient* per lattice point, value = interpolated dot products:

```glsl
vec2 grad(vec2 i) {
    float a = hash21(i) * 6.2831853;
    return vec2(cos(a), sin(a));
}

float perlin(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f*f*f*(f*(f*6.0-15.0)+10.0);      // quintic
    float a = dot(grad(i+vec2(0,0)), f-vec2(0,0));
    float b = dot(grad(i+vec2(1,0)), f-vec2(1,0));
    float c = dot(grad(i+vec2(0,1)), f-vec2(0,1));
    float d = dot(grad(i+vec2(1,1)), f-vec2(1,1));
    return mix(mix(a,b,u.x), mix(c,d,u.x), u.y) * 0.5 + 0.5;
}
```

**It is zero at every lattice point** (the offset vector is zero there), so the structure sits between the grid points rather than on it. Much better spectral characteristics than value noise.

**Simplex noise** uses a triangular (simplex) lattice instead of a hypercube: $n+1$ corners instead of $2^n$, so it scales as $O(n^2)$ rather than $O(2^n)$ in dimension, and has fewer directional artifacts. (Ken Perlin's 3D+ version was patented; the patent expired in 2022. OpenSimplex exists for the interim.)

**Worley / cellular noise** — distance to the nearest of a set of feature points. Distance to the *nearest* gives cell-like blobs; $F_2 - F_1$ gives the cell borders, which is where you get cracked earth, scales, and Voronoi patterns.

**fBm — fractional Brownian motion.** Sum octaves at doubling frequency and halving amplitude:

```glsl
float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 6; i++) {
        v += a * perlin(p);
        p *= 2.0;      // lacunarity
        a *= 0.5;      // gain
    }
    return v;
}
```

**This is a series expansion**, and the power spectrum follows $1/f^\beta$ — which is the statistical signature of a huge class of natural phenomena (terrain, clouds, coastlines, turbulence). That's why it looks natural: you are matching nature's spectrum, not imitating its appearance.

Variants: `abs(noise)` before summing gives **turbulence** (creases, flame); `1 - abs(noise)` gives **ridged** noise (mountain ridges).

**Aliasing in fBm.** Each octave doubles frequency; once an octave exceeds the pixel Nyquist rate it contributes only noise. Clamp the octave count to the sampling rate:

```glsl
float w = fwidth(p.x);
int octaves = int(clamp(-log2(w), 1.0, 8.0));
```

Or fade the last octave's amplitude smoothly. This is Module 5 again, applied to procedural content — and it's the difference between terrain that shimmers and terrain that doesn't.

**Domain warping** — evaluate noise at coordinates displaced by other noise:

```glsl
vec2 q = vec2(fbm(p), fbm(p + vec2(5.2, 1.3)));
float f = fbm(p + 4.0 * q);
```

Two levels give marbling and smoke. Three give something startlingly organic for how little code it is.

---

## 7.6 Raymarching (sphere tracing)

3D SDFs, rendered without geometry. The insight: because $|\nabla d| = 1$, $d(\mathbf{p})$ is the radius of a sphere around $\mathbf{p}$ guaranteed empty. So you can safely step that far.

```glsl
float march(vec3 ro, vec3 rd) {
    float t = 0.0;
    for (int i = 0; i < 128; i++) {
        vec3 p = ro + rd * t;
        float d = map(p);
        if (d < 0.001 * t) break;      // note: tolerance scales with distance
        if (t > MAX_DIST) break;
        t += d;
    }
    return t;
}
```

The `0.001 * t` tolerance is a Module 5 idea in disguise: at distance $t$ a pixel covers more world space, so demanding constant absolute precision wastes iterations and causes shimmer.

**Normals by central differences** on the field:

```glsl
vec3 calcNormal(vec3 p) {
    const vec2 e = vec2(1.0, -1.0) * 0.0005;
    return normalize(e.xyy*map(p + e.xyy) + e.yyx*map(p + e.yyx) +
                     e.yxy*map(p + e.yxy) + e.xxx*map(p + e.xxx));
}
```

That's the tetrahedron trick — 4 evaluations instead of 6.

**Soft shadows for free.** March toward the light and track the minimum ratio $d/t$ — that ratio is the angular size of the nearest occluder, which is exactly the penumbra:

```glsl
float softShadow(vec3 ro, vec3 rd, float k) {
    float res = 1.0, t = 0.01;
    for (int i = 0; i < 64; i++) {
        float h = map(ro + rd * t);
        res = min(res, k * h / t);
        t += clamp(h, 0.01, 0.2);
        if (res < 0.001) break;
    }
    return clamp(res, 0.0, 1.0);
}
```

Getting penumbrae from a shadow-ray query that returns a *distance* rather than a hit/miss is the single most elegant thing in the SDF toolkit.

**Ambient occlusion** similarly: sample the field along the normal and compare to the expected free distance.

---

## 7.7 The rendering equation

Kajiya, 1986. Everything in Module 0 returns.

$$L_o(\mathbf{x}, \omega_o) = L_e(\mathbf{x}, \omega_o) + \int_{H^2} f_r(\mathbf{x}, \omega_i, \omega_o)\, L_i(\mathbf{x}, \omega_i)\, (\omega_i \cdot \mathbf{n})\, d\omega_i$$

Term by term, with the module that defined each:

- $L_o$, $L_i$ — **radiance** (0.2). The privileged quantity.
- $L_e$ — emission.
- $\int_{H^2} \ldots d\omega_i$ — the hemisphere integral, with $d\omega = \sin\theta\,d\theta\,d\phi$ (0.3).
- $f_r$ — the BRDF, in sr⁻¹. Must obey **reciprocity** ($f_r(\omega_i,\omega_o) = f_r(\omega_o,\omega_i)$) and **energy conservation** ($\int f_r \cos\theta\, d\omega \le 1$).
- $(\omega_i\cdot\mathbf{n}) = \cos\theta$ — projected area (0.5). Geometry, not material.

It's a Fredholm integral equation of the second kind — $L$ appears on both sides, because light bounces. Expanding it as a Neumann series gives the path-tracing formulation: direct light + one bounce + two bounces + …

And the whole thing is *spectral*: strictly, $L$ and $f_r$ are functions of $\lambda$, and you should solve it per-wavelength and then project through $T$ (1.2). RGB rendering solves three samples of it and hopes (0.6, 3.3).

**Lambertian:** $f_r = \rho/\pi$. The $\pi$ is the projected solid angle of the hemisphere (0.3). You derived it in Exercise 0.1.

**Cook–Torrance microfacet:**

$$f_r = \frac{D(\mathbf{h})\,F(\omega_o,\mathbf{h})\,G(\omega_i,\omega_o)}{4(\omega_i\cdot\mathbf{n})(\omega_o\cdot\mathbf{n})}$$

$D$ = microfacet normal distribution (GGX/Trowbridge–Reitz), $F$ = Fresnel (Schlick's approximation), $G$ = geometric masking/shadowing (Smith). The $4$ in the denominator comes from the Jacobian of the half-vector transform — worth deriving once so it isn't a mystery constant.

---

## 7.8 Suggested build sequence

1. Aspect-correct UVs, a circle, and a `step` edge. Zoom in; observe the jaggies.
2. Replace with `smoothstep(w,-w,d)` using `fwidth`. Zoom again. Note it's correct at every zoom.
3. Build an SDF scene: union, subtraction, smooth union. Add outlines with `abs(d)`.
4. Add `mod()` domain repetition. Note the cost is zero.
5. Value noise → Perlin → fBm. Plot the power spectrum of each.
6. Domain warping. Two levels, then three.
7. Octave clamping by `fwidth`. Animate the camera and confirm the shimmer disappears.
8. Go to 3D: raymarch a sphere. Add normals, then Lambert, then soft shadows, then AO.
9. Do all shading in **linear light**, tone map with AgX (Module 5.6), encode with the sRGB OETF (5.4), dither 1 LSB with blue noise (5.5).
10. Palette everything in **Oklch** (Module 4.5).

Step 9 is the one people skip. Do it early and every subsequent image will look better than the equivalent Shadertoy.

---

## Exercises

**7.1** Plot `step`, linear, cubic smoothstep, and quintic on the same axes, along with their first and second derivatives. Identify visually which discontinuity causes which artifact.

**7.2** Build a shader that renders the same circle four ways: `step`, fixed-width `smoothstep`, `fwidth`-based, and 16× supersampled ground truth. Add a zoom uniform. Compute per-pixel error against ground truth and display it as a heatmap.

**7.3** Implement `sdBox` and explain, line by line, why the two-term formula produces correct distance both inside and outside. Then extend to `sdRoundedBox` and `sdHexagon`.

**7.4** Implement `opSmoothUnion` and plot $d$ along a line through the seam for $k = 0, 0.1, 0.5$. Verify $|\nabla d|$ stays near 1 (it degrades — find out by how much and what that costs a raymarcher).

**7.5** Implement value, Perlin, and Worley noise. FFT each and plot the radially-averaged power spectrum. Confirm Perlin's is band-limited and value noise's has lattice spikes.

**7.6** Implement fBm with adjustable lacunarity and gain. Sweep gain from 0.2 to 0.8 and fit the resulting power spectra to $1/f^\beta$. Relate $\beta$ to the gain analytically.

**7.7** Implement octave clamping. Render an infinite fBm terrain plane in perspective, animated. Toggle the clamp on and off and record video of the horizon. This exercise makes Module 5 emotionally real.

**7.8** Domain-warp fBm with two and three levels. Then colorize the result using an Oklch ramp with monotonic $L$. Compare against colorizing in HSV.

**7.9** Build a raymarched scene: smooth-unioned primitives, tetrahedron normals, soft shadows, AO. Then implement the full output chain — linear shading → AgX → sRGB OETF → blue-noise dither. Render with and without the chain and put them side by side.

**7.10** Implement a Lambertian BRDF and numerically verify energy conservation: Monte Carlo integrate $\int f_r \cos\theta\, d\omega$ over the hemisphere and confirm it equals $\rho$. Then do the same for GGX and find where your implementation loses energy (it will — single-scattering GGX always does at high roughness).

---

## Checkpoint

- Why is `smoothstep` cubic specifically, and when do you need quintic?
- Why does `smoothstep(w, -w, d)` antialias correctly at every zoom level?
- Why is Perlin noise zero at lattice points?
- Why does fBm look natural?
- Why does the rendering equation have a $\cos\theta$ but a Lambertian BRDF have a $1/\pi$?

---

## Where to go next

You now have the spine. The natural continuations:

- **Physically based rendering** — Pharr, Jakob & Humphreys, *PBRT* (free online). The rendering equation, solved properly.
- **Monte Carlo integration and importance sampling** — the actual content of modern rendering. Veach's thesis is still the reference.
- **Real-time techniques** — deferred/clustered shading, temporal accumulation (TAA is Module 5's sampling theory in the time domain), screen-space methods.
- **Signal processing proper** — Fourier, wavelets. Everything in Module 5 gets deeper.
- **Color appearance models** — CIECAM02/16, if you want to go past Oklab into surround effects and adaptation.

← [Module 6: The GPU Pipeline](06-gpu-pipeline.md) | [Back to README](README.md)
