# Module 1 — The Eye: Why Three Numbers Suffice

**Goal:** understand color vision as a linear map $\mathbb{R}^\infty \to \mathbb{R}^3$, and understand metamerism as that map's null space. This is the conceptual keystone of the whole course. Everything in Module 2 is a consequence.

---

## 1.1 The apparatus, briefly

Light passes through cornea, lens, and vitreous humor — all of which absorb, particularly in the UV — before reaching the retina. Two receptor families:

- **Rods** — ~120 million, one photopigment, saturate in daylight. Drive scotopic vision. Achromatic, high sensitivity, low acuity. Not involved in color as we'll model it.
- **Cones** — ~6 million, three photopigments, concentrated in the fovea. Drive photopic vision.

Cone types, named by peak sensitivity:

| Type | Peak $\lambda$ | Population | Also called |
|---|---|---|---|
| **L** | ~565 nm | ~64% | ρ, "red" |
| **M** | ~540 nm | ~32% | γ, "green" |
| **S** | ~440 nm | ~4% | β, "blue" |

Two things worth noticing immediately.

**L and M overlap enormously.** Their peaks are 25 nm apart, and their response curves are nearly congruent. The genes are adjacent on the X chromosome and ~96% identical — the M/L split is an evolutionarily recent duplication in Old World primates. This is why red–green color blindness is common (X-linked, and the genes are prone to unequal crossing over), and why the "red" and "green" labels are misleading: the L cone's peak is in yellow-green, nowhere near red.

**S cones are sparse and absent from the very center of the fovea.** Blue is spatially low-resolution. Chroma subsampling in JPEG and video codecs exploits exactly this, and so does subpixel text rendering.

---

## 1.2 Cone response as an inner product

Each cone type has a **spectral sensitivity function**: $\bar{l}(\lambda)$, $\bar{m}(\lambda)$, $\bar{s}(\lambda)$. These are the *cone fundamentals* (Stockman & Sharpe 2000 is the modern standard set; get them from CVRL).

Given incoming light $\Phi(\lambda)$, the response of each cone class is:

$$L = \int \Phi(\lambda)\,\bar{l}(\lambda)\,d\lambda \qquad
M = \int \Phi(\lambda)\,\bar{m}(\lambda)\,d\lambda \qquad
S = \int \Phi(\lambda)\,\bar{s}(\lambda)\,d\lambda$$

**Each of these is an inner product** $\langle \Phi, \bar{l}\rangle$ in the function space $L^2([380,780])$.

So define the operator:

$$T: L^2 \to \mathbb{R}^3, \qquad T[\Phi] = (\langle\Phi,\bar{l}\rangle, \langle\Phi,\bar{m}\rangle, \langle\Phi,\bar{s}\rangle)$$

$T$ is **linear**. That single fact generates the entire field of colorimetry.

Discretized at 5 nm from 380 to 780, $\Phi$ becomes a vector in $\mathbb{R}^{81}$ and $T$ becomes a $3\times 81$ matrix. Now you can just look at it as ordinary linear algebra — which you should, at least once, in code.

---

## 1.3 Metamerism is the null space

$T$ maps an 81-dimensional space to a 3-dimensional one. By rank–nullity:

$$\dim(\ker T) = 81 - 3 = 78$$

**Two spectra look identical if and only if their difference lies in $\ker T$.**

$$T[\Phi_1] = T[\Phi_2] \iff \Phi_1 - \Phi_2 \in \ker T$$

Such a pair is a **metameric pair**, and the difference is a **metameric black** — a nonzero spectral distribution that is, to the human visual system, indistinguishable from no light at all. (Physically it must contain negative regions, so a metameric black is never realizable as light on its own — only as a difference.)

This is not a curiosity. It is the entire reason display technology works. Your monitor cannot reproduce the spectrum of a lemon. It reproduces a metamer of it: three narrow-ish primaries whose weighted sum lands on the same point in $\mathbb{R}^3$. Every image you have ever seen on a screen is a lie that exploits a 78-dimensional null space.

**Consequences to internalize:**

- **Illuminant metameric failure.** Two objects match under D65 and differ under incandescent, because reflectance multiplies the illuminant *before* the projection: $T[\Phi_{illum} \cdot R(\lambda)]$. Change $\Phi_{illum}$ and the difference no longer lies in the null space. This is why you take fabric samples to the window.
- **Observer metameric failure.** Cone fundamentals vary between individuals (macular pigment density, lens yellowing with age, polymorphism in the L opsin). Your null space isn't quite mine.
- **Color rendering index** exists to quantify how badly a light source distorts these relationships.

---

## 1.4 Grassmann's laws

Empirical, from 1853, and they amount to the statement "$T$ is linear":

1. **Symmetry:** if A matches B, B matches A.
2. **Transitivity:** if A matches B and B matches C, A matches C.
3. **Proportionality:** if A matches B, then $\alpha$A matches $\alpha$B.
4. **Additivity:** if A matches B and C matches D, then A+C matches B+D.

Additivity and proportionality are exactly linearity. This is why color mixing can be done with matrices at all, and it is a *contingent empirical fact* about the visual system, not a mathematical necessity. It's also approximate — it breaks at very low and very high luminance and under strong chromatic adaptation.

---

## 1.5 The dimensionality is a choice nature made

Trichromacy is not universal:

- Most mammals: **dichromatic** (2 cones). Dogs, cats, horses.
- Birds, many reptiles, some fish: **tetrachromatic**, often with a UV cone. Their null space is $\dim = n - 4$. Bird plumage that looks plain to us can be dramatically patterned to them, and your monitor cannot fake it.
- Mantis shrimp: 12+ photoreceptor classes — though evidence suggests they do less discrimination with them than the count implies, using them more as a hardwired classifier than a comparison system.
- A minority of human women carrying a variant L opsin on one X may be functionally **tetrachromatic**.

The lesson: "color" is not a property of light. It is the shape of a particular projection. A different projection is a different color world, and the mathematics is identical — only the dimension changes.

---

## 1.6 Opponent processing: the second transform

Cones do not send L, M, S to the brain. The retina immediately recodes them into **opponent channels** (Hering, 1892; confirmed physiologically in the 1950s):

$$\begin{aligned}
\text{Achromatic } (A) &\approx L + M \\
\text{Red–Green } (RG) &\approx L - M \\
\text{Yellow–Blue } (YB) &\approx (L + M) - S
\end{aligned}$$

Roughly, in matrix form:

$$\begin{bmatrix} A \\ RG \\ YB \end{bmatrix} =
\begin{bmatrix} 1 & 1 & 0 \\ 1 & -1 & 0 \\ 0.5 & 0.5 & -1 \end{bmatrix}
\begin{bmatrix} L \\ M \\ S \end{bmatrix}$$

Another change of basis. Why the visual system bothers:

- **Decorrelation.** L and M responses are highly correlated (their curves overlap). Differencing them removes redundancy — this is essentially a PCA of natural image statistics, done in wetware.
- **Bandwidth.** The optic nerve has ~1 million fibers for ~6 million cones. Compression is mandatory.
- **It explains phenomenology.** There is no reddish-green and no yellowish-blue, because those are opposite signs of a single channel. There are exactly four unique hues (red, green, yellow, blue) because there are two chromatic axes with two poles each.

**This is why YCbCr, YUV, Lab, and Oklab all exist.** Every perceptual color space separates luminance from two chromatic axes, because that is what the retina does. Chroma subsampling (4:2:0) works because the chromatic channels are genuinely lower-bandwidth in the visual system.

---

## 1.7 The nonlinearity: response compression

So far $T$ is linear. Perception is not.

**Weber's law:** the just-noticeable difference is proportional to the stimulus.

$$\frac{\Delta I}{I} = k$$

**Fechner's extension:** integrating Weber gives a logarithmic response, $P = k\ln(I/I_0)$.

**Stevens' power law** fits the data better across most modalities:

$$P = k I^{a}$$

For brightness, $a \approx 0.33$–$0.5$ depending on conditions and adapting field.

Two enormous consequences:

**1. Perceptual coding.** Because the eye is more sensitive to relative differences in the dark than in the light, a linear 8-bit encoding wastes codes in highlights and bands in shadows. Encoding with a $\approx x^{1/2.2}$ curve distributes quantization error perceptually evenly. **This is the real reason gamma encoding exists.** The CRT's response curve was a historical coincidence that happened to match; it is not the justification.

**2. Adaptation.** The visual system normalizes against the local mean. This is why a display at 100 nits can represent a sunlit scene at 10,000 nits, why lightness constancy works, and why simultaneous contrast illusions exist. The system reports *ratios*, not absolutes.

We will formalize the $\approx x^{1/3}$ compression as the cube root inside CIELAB (Module 2) and Oklab (Module 4).

---

## 1.8 Code: build the projection yourself

Do this before Module 2. It takes an hour and makes the abstraction concrete.

```python
import numpy as np

# lambdas: (81,) from 380 to 780 in 5nm steps
# lms:     (81, 3) Stockman-Sharpe cone fundamentals, energy units
# Get these from cvrl.org

def project(spd, lms, d_lambda=5.0):
    """SPD (81,) -> LMS (3,).  This is the map T."""
    return (spd[:, None] * lms).sum(axis=0) * d_lambda

T = lms.T * 5.0          # (3, 81) -- the matrix form of T

# --- Metameric black: find the null space, look at it ---
U, S, Vt = np.linalg.svd(T)
null_basis = Vt[3:]      # (78, 81) -- orthonormal basis for ker T
print(S[:5])             # first 3 nonzero, rest ~0

black = null_basis[0]
assert np.allclose(T @ black, 0, atol=1e-9)
# Plot `black`. It oscillates and goes negative. That is a metameric black.

# --- Construct a metameric pair ---
base  = some_smooth_spd                  # (81,)
other = base + 0.3 * black
assert np.allclose(T @ base, T @ other)  # identical to the eye
# Plot both. They look nothing alike as curves. Same color.

# --- Illuminant metameric failure ---
# Treat base/other as reflectances now, and re-project under two illuminants.
for illum in (D65, illuminant_A):
    print(T @ (illum * base), T @ (illum * other))   # now they differ
```

If you plot a metameric pair on the same axes and understand why they produce the same sensation, you have the central idea of this course.

---

## Exercises

**1.1** Load the Stockman–Sharpe fundamentals. Plot them. Confirm the L/M overlap visually and compute the correlation coefficient between $\bar{l}$ and $\bar{m}$ over the sampled range. (It's high — this is why the RG opponent channel is informative.)

**1.2** Compute $\operatorname{rank}(T)$ numerically via SVD and confirm it is 3. Note the ratio of the third singular value to the first — this quantifies how much weaker the S-cone channel is.

**1.3** Generate a metameric pair as in the code above. Then generate a *physically realizable* one: find nonnegative $\Phi_1 \ne \Phi_2$ with $T\Phi_1 = T\Phi_2$, using constrained optimization. Note how much harder the nonnegativity constraint makes it — and that this constraint is exactly what a display's primaries face.

**1.4** Simulate dichromacy. Drop the M row from $T$, then reconstruct: find, for each input color, the nearest color in the space spanned by the remaining two fundamentals. Render an image through it. Compare with published Brettel–Viénot–Mollon simulations and note where yours diverges.

**1.5** Take a Macbeth ColorChecker's published reflectance spectra. Project them under D65 and under Illuminant A. Find the pair of patches whose LMS distance changes most between the two illuminants — you've found a metameric-failure-prone pair.

**1.6** Implement Stevens' law with $a = 0.4$ and plot it against a $\log$ curve and against $x^{1/2.2}$ over $[0.001, 1]$. Where do they agree? Where does the choice matter for an 8-bit encoding?

---

## Checkpoint

- Why can three primaries reproduce (most) colors, when light has infinite degrees of freedom?
- What, precisely, is a metameric black, and why can't you buy a flashlight that emits one?
- Why do two shirts match in the store and clash outside?
- Why is there no such color as reddish-green?
- Why does gamma encoding exist? (Hint: the answer is not "CRTs.")

← [Module 0: Radiometry](00-radiometry.md) | → [Module 2: Colorimetry](02-colorimetry.md)
