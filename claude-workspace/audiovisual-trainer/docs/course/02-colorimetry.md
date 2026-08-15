# Module 2 — Colorimetry: Building Coordinate Systems

**Goal:** derive CIE XYZ, understand chromaticity as a projective divide, and be able to construct any RGB→XYZ matrix from primaries and a white point without looking one up.

---

## 2.1 Color matching experiments

Wright (1928) and Guild (1931): show an observer a split field. One half is a monochromatic test light at wavelength $\lambda$. The other half is a mix of three fixed primaries (700 nm, 546.1 nm, 435.8 nm). The observer adjusts the three primary intensities until the halves match.

The resulting amounts, as functions of $\lambda$, are the **color matching functions** $\bar{r}(\lambda), \bar{g}(\lambda), \bar{b}(\lambda)$.

**Critical finding: some matches require negative amounts.** For cyans around 500 nm, no positive combination of the primaries works. The observer instead adds primary light to the *test* side — which, by Grassmann's laws, is algebraically a negative contribution.

This is not an experimental defect. It is a proof: **no set of three physically realizable primaries can span the full gamut of human vision.** The reason is that the cone fundamentals overlap. There is no light that stimulates M without also stimulating L, so the "pure M" direction in LMS space is not physically reachable. Every real display gamut is a strict subset. This is a permanent constraint, not an engineering problem awaiting a solution.

CMFs relate to cone fundamentals by a fixed linear transform — they are the same information in a different basis, since both are derived from the same underlying $T$.

---

## 2.2 CIE 1931 XYZ

Negative numbers were intolerable for 1931 hand computation, so the CIE applied a change of basis to imaginary primaries chosen so that:

1. All CMFs are **nonnegative** everywhere.
2. $\bar{y}(\lambda) = V(\lambda)$ **exactly** — so $Y$ *is* luminance, by construction.
3. Equal-energy white ($\Phi \equiv 1$) maps to $X = Y = Z$.

The X, Y, Z primaries are outside the space of realizable colors — they are **imaginary**. That's fine; a basis need not consist of achievable vectors.

$$X = \int \Phi(\lambda)\bar{x}(\lambda)d\lambda \qquad
Y = \int \Phi(\lambda)\bar{y}(\lambda)d\lambda \qquad
Z = \int \Phi(\lambda)\bar{z}(\lambda)d\lambda$$

For a reflective object, $\Phi(\lambda) = I(\lambda)R(\lambda)$ and you normalize so a perfect diffuser gives $Y = 100$:

$$Y = 100 \cdot \frac{\int I(\lambda)R(\lambda)\bar{y}(\lambda)d\lambda}{\int I(\lambda)\bar{y}(\lambda)d\lambda}$$

**Observers:** the CIE 1931 **2°** observer models foveal viewing; the CIE 1964 **10°** observer models a wider field and differs meaningfully in the blue. Graphics almost universally uses 2°. State which one you're using — mismatched observers are a quiet source of discrepancy.

---

## 2.3 Chromaticity is a perspective divide

XYZ mixes "how much" with "what kind." Separate them:

$$x = \frac{X}{X+Y+Z}, \qquad y = \frac{Y}{X+Y+Z}, \qquad z = \frac{Z}{X+Y+Z} = 1-x-y$$

**This is a projective projection.** The set of all scalar multiples of an XYZ vector is a ray from the origin — a point in $\mathbb{P}^2$. Dividing by $X+Y+Z$ picks the representative on the plane $X+Y+Z=1$; $(x,y)$ is that plane's coordinates.

It is *literally the same operation* as the perspective divide in the graphics pipeline. There, $(x,y,z,w) \mapsto (x/w, y/w, z/w)$ collapses a ray through the eye to a point on the image plane. Here, $(X,Y,Z)$ collapses a ray of intensities to a point of chroma. Same geometry, different application.

Recovery needs the discarded magnitude back:

$$X = \frac{x}{y}Y, \qquad Z = \frac{1-x-y}{y}Y$$

The **CIE 1931 chromaticity diagram** is the horseshoe you've seen. Its boundary:

- **Spectral locus** — the curve traced by monochromatic light, $\lambda$ from 380 to 700 nm.
- **Line of purples** — the straight chord closing it. These are non-spectral: no single wavelength produces magenta. Magenta is a hole in the spectrum, perceived as a color.

The region is **convex**, because it is the convex hull of the spectral locus, and any light is a nonnegative combination of monochromatic components.

**Warning about this diagram:** it is perceptually badly non-uniform. The green region occupies an enormous area that is perceptually small; blue is crushed. MacAdam ellipses (regions of indistinguishable color) vary by more than an order of magnitude in size across the diagram. Never use xy distance as a color difference metric. CIE 1976 u'v' is a modest improvement:

$$u' = \frac{4X}{X+15Y+3Z}, \qquad v' = \frac{9Y}{X+15Y+3Z}$$

---

## 2.4 Gamuts are triangles, mixing is barycentric

Given three primaries at chromaticities $(x_R,y_R), (x_G,y_G), (x_B,y_B)$, the set of reproducible chromaticities is exactly the **triangle** they span. Additive mixing is a convex combination, and convex combinations of three points fill a triangle.

Standard gamuts:

| Space | Red | Green | Blue | White |
|---|---|---|---|---|
| **sRGB / Rec.709** | (0.640, 0.330) | (0.300, 0.600) | (0.150, 0.060) | D65 (0.3127, 0.3290) |
| **Display P3** | (0.680, 0.320) | (0.265, 0.690) | (0.150, 0.060) | D65 |
| **Adobe RGB** | (0.640, 0.330) | (0.210, 0.710) | (0.150, 0.060) | D65 |
| **Rec.2020** | (0.708, 0.292) | (0.170, 0.797) | (0.131, 0.046) | D65 |
| **ACES AP0** | (0.7347, 0.2653) | (0.0, 1.0) | (0.0001, −0.0770) | ACES (~D60) |

Note ACES AP0 has primaries *outside* the spectral locus — imaginary, deliberately, so the gamut encloses all visible color. Negative and >1 values are normal in a working space.

Determining whether a color is in gamut is a barycentric coordinate test: solve for weights, check all three are in $[0,1]$.

---

## 2.5 Deriving an RGB→XYZ matrix

Do not paste this matrix. Derive it. It takes fifteen lines and you'll never be confused about color spaces again.

**Setup.** Each primary has a known chromaticity but unknown absolute scale. Build the direction of each primary in XYZ from its chromaticity, then find the scale factors that make the primaries sum to the white point.

**Step 1** — convert each primary's $(x,y)$ to an XYZ direction at $Y=1$:

$$\mathbf{P}_i = \left(\frac{x_i}{y_i},\ 1,\ \frac{1-x_i-y_i}{y_i}\right)$$

Assemble as columns:

$$M_{dir} = \begin{bmatrix} | & | & | \\ \mathbf{P}_R & \mathbf{P}_G & \mathbf{P}_B \\ | & | & | \end{bmatrix}$$

**Step 2** — the white point in XYZ, at $Y=1$:

$$\mathbf{W} = \left(\frac{x_W}{y_W},\ 1,\ \frac{1-x_W-y_W}{y_W}\right)$$

**Step 3** — require that $R=G=B=1$ produces white. Solve for the scale vector $\mathbf{s}$:

$$M_{dir}\,\mathbf{s} = \mathbf{W} \quad\Longrightarrow\quad \mathbf{s} = M_{dir}^{-1}\mathbf{W}$$

**Step 4** — scale the columns:

$$M = M_{dir} \cdot \operatorname{diag}(\mathbf{s})$$

Now $\mathbf{XYZ} = M \cdot \mathbf{RGB}_{linear}$, and $M^{-1}$ goes back.

```python
import numpy as np

def rgb_to_xyz_matrix(prim_xy, white_xy):
    """prim_xy: 3x2 array of (x,y) for R,G,B.  white_xy: (x,y)."""
    def to_XYZ(xy):
        x, y = xy
        return np.array([x / y, 1.0, (1.0 - x - y) / y])
    M_dir = np.column_stack([to_XYZ(p) for p in prim_xy])
    W = to_XYZ(white_xy)
    s = np.linalg.solve(M_dir, W)
    return M_dir * s          # broadcasts across columns

sRGB = rgb_to_xyz_matrix(
    [(0.640, 0.330), (0.300, 0.600), (0.150, 0.060)],
    (0.3127, 0.3290))
print(np.round(sRGB, 6))
```

You should get (to rounding):

$$M_{sRGB} = \begin{bmatrix}
0.412456 & 0.357576 & 0.180438 \\
0.212673 & 0.715152 & 0.072175 \\
0.019334 & 0.119192 & 0.950304
\end{bmatrix}$$

**Look at the middle row.** $(0.2126, 0.7152, 0.0722)$ — that's the luminance coefficient vector you've seen in a hundred grayscale conversions. It is not a magic constant. It is row 2 of this matrix, and row 2 is $Y$, and $\bar{y} = V(\lambda)$. It came from the eye.

Two persistent errors worth naming:
- Using $(0.299, 0.587, 0.114)$ — those are the **Rec.601** coefficients, for a different (older, NTSC) set of primaries. Wrong for sRGB content.
- Applying either set to **gamma-encoded** values. Luminance is a linear-light quantity. Decode first. (Module 3 belabors this.)

---

## 2.6 White points and chromatic adaptation

A **white point** is the chromaticity that the observer, adapted to the scene, calls white. Standard illuminants:

| Illuminant | Description | $(x, y)$ | CCT |
|---|---|---|---|
| A | Tungsten | (0.4476, 0.4074) | 2856 K |
| D50 | Horizon daylight — print standard | (0.3457, 0.3585) | 5003 K |
| D65 | Noon daylight — display standard | (0.3127, 0.3290) | 6504 K |
| E | Equal energy (theoretical) | (1/3, 1/3) | ~5454 K |

**Correlated color temperature** is the temperature of the blackbody nearest (in u'v') to a given chromaticity. It's a 1D projection of a 2D quantity, so it's lossy — two lights with the same CCT can look noticeably different. **Duv** measures the perpendicular distance from the Planckian locus and is the missing second coordinate.

**Chromatic adaptation transform (CAT).** To move a color from one white point to another, the standard move is: transform to a sharpened cone-like space, scale each channel by the ratio of white points (von Kries), transform back.

$$M_{adapt} = M_{CAT}^{-1} \cdot \operatorname{diag}\!\left(\frac{\rho_{dst}}{\rho_{src}}, \frac{\gamma_{dst}}{\gamma_{src}}, \frac{\beta_{dst}}{\beta_{src}}\right) \cdot M_{CAT}$$

The **Bradford** matrix is the standard $M_{CAT}$:

$$M_{Bradford} = \begin{bmatrix}
0.8951 & 0.2664 & -0.1614 \\
-0.7502 & 1.7135 & 0.0367 \\
0.0389 & -0.0685 & 1.0296
\end{bmatrix}$$

It's "sharpened" — more spectrally selective than actual cone fundamentals — because that empirically predicts adaptation better. This is what "white balance" is doing, and it's why a D50→D65 conversion is a matrix and not a scale.

---

## 2.7 Perceptual uniformity: CIELAB

XYZ is linear in light, which means it is badly nonlinear in perception. CIELAB (1976) applies the cube-root compression from Module 1.7 and an opponent-channel structure from Module 1.6.

With $X_n, Y_n, Z_n$ the white point:

$$f(t) = \begin{cases}
t^{1/3} & t > \delta^3 \\
\frac{t}{3\delta^2} + \frac{4}{29} & \text{otherwise}
\end{cases}, \qquad \delta = \frac{6}{29}$$

$$L^* = 116\,f(Y/Y_n) - 16$$
$$a^* = 500\,\big(f(X/X_n) - f(Y/Y_n)\big)$$
$$b^* = 200\,\big(f(Y/Y_n) - f(Z/Z_n)\big)$$

The linear segment near zero prevents the infinite slope of $t^{1/3}$ at the origin from amplifying noise.

$L^*$ runs 0–100. $L^* = 50$ is middle gray at about 18.4% linear luminance — the origin of the photographer's 18% gray card.

**Color difference:**

$$\Delta E^*_{ab} = \sqrt{(\Delta L^*)^2 + (\Delta a^*)^2 + (\Delta b^*)^2}$$

$\Delta E \approx 1$ is roughly a just-noticeable difference. Roughly. CIELAB is only approximately uniform — it's notably poor in saturated blues, where it exhibits a hue shift toward purple during lightness interpolation. CIEDE2000 patches this with lightness, chroma, and hue weighting terms plus a rotation term for the blue region. It is ugly, empirical, unsuitable for interpolation, and the current standard for *measuring* difference. Use CIEDE2000 to measure, Oklab (Module 4) to interpolate.

---

## 2.8 The full pipeline

```
SPD Φ(λ)
   │  ∫ against x̄ȳz̄            [Module 1: the projection]
   ▼
 XYZ  ──── /(X+Y+Z) ───▶ xy chromaticity   [projective divide]
   │
   │  × M⁻¹                      [change of basis]
   ▼
linear RGB
   │  × OETF                     [Module 5: perceptual coding]
   ▼
encoded RGB  ── 8 bits ─▶  framebuffer
```

Every arrow is invertible except the first (that's the null space) and the last (that's quantization).

---

## Exercises

**2.1** Implement `rgb_to_xyz_matrix`. Derive matrices for sRGB, Display P3, and Rec.2020. Verify each maps $(1,1,1)$ to its white point. Verify $M_{P3}^{-1}M_{sRGB}$ converts sRGB to P3 and that pure sRGB red lands inside the P3 triangle.

**2.2** Render the chromaticity diagram. For each pixel $(x,y)$, set $Y=1$, convert to XYZ, then to linear sRGB, then encode. Clip out-of-gamut values — and notice how much of the diagram clips. Overlay the spectral locus from the CMF tables and the sRGB / P3 / Rec.2020 triangles.

**2.3** Using your Planck's law code from Exercise 0.3, trace the **Planckian locus** on the diagram for $T \in [1000, 20000]$ K. Then implement CCT lookup: given a chromaticity, find the nearest blackbody in u'v'. Compute Duv.

**2.4** Implement the Bradford CAT. Convert a D65 sRGB image to a D50 working space and back; verify round-trip error. Then apply a deliberate A→D65 adaptation to a tungsten-lit photo and observe it white-balance.

**2.5** Implement CIELAB and $\Delta E^*_{ab}$. Then implement CIEDE2000. Find a pair of colors where the two metrics disagree by more than 2× — the saturated-blue region is a good hunting ground.

**2.6** **Gamut mapping.** Take an out-of-gamut Rec.2020 color and map it into sRGB three ways: (a) naive per-channel clip, (b) clip in LCh preserving hue and lightness, reducing chroma, (c) project toward the white point. Render a swatch grid comparing them. This exercise will do more for your intuition than reading about it.

**2.7** Compute XYZ for the Macbeth ColorChecker patches from their spectral reflectances under D65, convert to sRGB, and render the chart. Compare against published sRGB values. Diagnose any mismatch: observer? illuminant normalization? integration step?

---

## Checkpoint

- Why did color matching require negative primary amounts, and what does that prove?
- Why is $Y$ luminance and not just "the green channel"?
- Where does $(0.2126, 0.7152, 0.0722)$ come from?
- Why is the chromaticity diagram's green region so large?
- Why can't you compare colors by Euclidean distance in xy?

← [Module 1: The Eye](01-the-eye.md) | → [Module 3: Additive & Subtractive](03-additive-subtractive.md)
