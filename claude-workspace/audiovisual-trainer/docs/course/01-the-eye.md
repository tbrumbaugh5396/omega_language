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

### What a photoreceptor actually does: retinal isomerization

You can do all of colorimetry without this, but the mechanism explains several facts that otherwise look arbitrary — especially why the L and M curves sit so close together.

**The molecule.** All vertebrate visual pigments use **retinal** (C₂₀H₂₈O), vitamin A aldehyde, derived from β-carotene. It's a polyene: alternating single and double bonds forming a delocalized conjugated π-electron system. That system absorbs the photon, and its electronic structure sets the absorption wavelength.

**Resting state.** Retinal sits in the 11-*cis* configuration — kinked at the C11=C12 double bond — covalently tethered inside a binding pocket of the **opsin** protein through a protonated Schiff base linkage to a lysine residue (Lys296 in bovine rhodopsin). Chromophore plus protein together are the visual pigment.

**The photon event.** Absorption promotes an electron from the HOMO to the LUMO of the π system. In the ground state the C11=C12 bond has strong π character and resists rotation; in the excited state the π* orbital has a node there, bond order collapses, and rotation becomes nearly free.

The molecule twists from 11-*cis* to all-*trans* in about **200 femtoseconds**, passing through a conical intersection between the excited and ground state surfaces. It's among the fastest known photochemical reactions, essentially ballistic rather than diffusive, with a quantum yield of ~0.65 — two of every three absorbed photons produce isomerization.

**The shape change.** 11-*cis* is bent, all-*trans* is straight: a few ångströms of extension inside a snug pocket. The strained protein relaxes through a series of spectroscopically distinct intermediates (photo-, batho-, lumi-, meta-I) to **metarhodopsin II**, the active signaling state, in milliseconds.

**Amplification.** Metarhodopsin II activates the G protein transducin; each transducin activates a cGMP phosphodiesterase; each PDE hydrolyzes thousands of cGMP per second. cGMP concentration falls, cGMP-gated cation channels close, and sodium/calcium influx stops.

Note the polarity: photoreceptors are **depolarized in the dark** (the "dark current") and *hyperpolarize* under light, releasing *less* neurotransmitter — backwards from most sensory neurons. Total cascade gain is roughly 10⁶ cGMP hydrolyzed per absorbed photon, which is why rods respond to **single photons**. Hecht, Shlaer and Pirenne inferred this psychophysically in 1942; Baylor recorded single-photon responses directly in 1979.

**Recovery, and why dark adaptation is slow.** All-*trans* retinal dissociates, is reduced to all-*trans* retinol, shuttled to the retinal pigment epithelium, re-isomerized to 11-*cis* by the RPE65 enzyme, and returned. This **visual cycle** runs on seconds to minutes. Bright light depletes the 11-*cis* pool (bleaching), and rebuilding it is why full dark adaptation takes 20–30 minutes.

### Spectral tuning: three cones, one molecule

**L, M, and S cones all use the identical retinal molecule.** They differ only in the opsin protein wrapped around it.

Charged and polar residues near the Schiff base and along the polyene chain shift the ground-to-excited-state energy gap — the **opsin shift** — tuning the same chromophore anywhere from ~360 nm (avian and insect UV receptors) to ~630 nm (some fish).

This resolves the L/M puzzle above. Human L and M opsins differ at only a handful of functionally important sites; positions 180, 277, and 285 account for most of the ~25 nm separation. A gene duplication plus a few substitutions is a very cheap evolutionary move, which is why the M/L split arose recently and independently in multiple primate lineages — and why unequal crossing over between two nearly-identical adjacent genes on the X chromosome makes red-green deficiency so common.

It also means the cone fundamentals you are about to integrate are, physically, **three tunings of one molecule.** And rhodopsin's ~500 nm absorption peak is not a coincidental match to the scotopic $V'(\lambda)$ curve peaking at 507 nm — that curve *is* rhodopsin's absorption spectrum, measured psychophysically.

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

### Deflate it: three weighted sums

Strip the integrals away entirely. The sample count is $(780-380)/5 + 1 = 81$, so a light is a list of 81 numbers and each cone response is a dot product:

$$L = \sum_{k=1}^{81} \Phi_k\, \bar{l}_k \cdot \Delta\lambda$$

Stack the three weight vectors as rows:

$$T = \Delta\lambda \begin{bmatrix} \text{—}\ \bar{l}\ \text{—} \\ \text{—}\ \bar{m}\ \text{—} \\ \text{—}\ \bar{s}\ \text{—} \end{bmatrix}, \qquad \begin{bmatrix}L\\M\\S\end{bmatrix} = T\,\Phi$$

**The entire visual front end is three weighted sums of an 81-number list.** Everything that follows in this module and the next is undergraduate linear algebra applied to that matrix. If any of it starts feeling mystical, come back here.

---

## 1.3 Metamerism is the null space

### Rank–nullity, and a number that's slightly a lie

For any linear map, $\dim(\text{domain}) = \operatorname{rank}(T) + \dim(\ker T)$. Here the domain is $\mathbb{R}^{81}$ and the rank is 3, so:

$$\dim(\ker T) = 81 - 3 = 78$$

**Take that 78 with a grain of salt — it is an artifact of the sampling choice.** At 1 nm you get 401 components and nullity 398; at 10 nm, 41 and 38. In the continuous setting $L^2([380,780])$ the kernel is genuinely infinite-dimensional.

The sampling-independent statement — the actual content of trichromacy — is the **codimension**:

$$\operatorname{codim}(\ker T) = 3, \qquad L^2/\ker T \cong \mathbb{R}^3$$

Read "78" as shorthand for "almost everything." What's invariant is that exactly three degrees of freedom survive.

**Why is the rank exactly 3?** Because $\bar{l}, \bar{m}, \bar{s}$ are linearly independent — none is a combination of the other two — so $T$ has full row rank and its SVD returns exactly three nonzero singular values.

But full rank is not the same as well-conditioned. $\bar{l}$ and $\bar{m}$ overlap heavily (correlation above 0.9), so the third singular direction is weakly determined. The space is genuinely 3D, but one dimension is thin. That thinness is why observer metamerism is a practical problem and why S-cone-dominated discriminations are noisy.

### Computing the kernel

The cleanest characterization: $\ker T$ is the **orthogonal complement of the row space**.

$$\ker T = \big(\operatorname{span}\{\bar{l}, \bar{m}, \bar{s}\}\big)^\perp$$

In words: **a metameric black is any spectrum orthogonal to all three color matching functions.** Three constraints, 81 unknowns, 78 free.

(Technical caveat: "orthogonal" means under the inner product that discretizes $L^2$. With uniform sampling that's the ordinary dot product. Sample non-uniformly and you need the corresponding weighted inner product, or your kernel will be subtly wrong.)

Three practical routes:

```python
# 1. SVD — rows 4 onward of V^T span the kernel
U, S, Vt = np.linalg.svd(T)              # T is (3, 81)
null_basis = Vt[3:]                      # (78, 81), orthonormal
assert np.allclose(T @ null_basis.T, 0)

# 2. Explicit projector onto the row space (T has full row rank)
P = T.T @ np.linalg.inv(T @ T.T) @ T     # (81, 81), rank 3
Q = np.eye(81) - P                       # projects ONTO the kernel

# 3. Wyszecki's decomposition — split any spectrum in two
phi_fundamental = P @ phi   # 3 DOF: determines the color
phi_black       = Q @ phi   # 78 DOF: completely invisible
```

The third is the conceptual payoff. Every spectrum splits uniquely:

$$\Phi = \underbrace{P\Phi}_{\text{determines the color}} + \underbrace{(I-P)\Phi}_{\text{invisible}}$$

Verify by hand: $T(I-P)\Phi = T\Phi - TT^\mathsf{T}(TT^\mathsf{T})^{-1}T\Phi = T\Phi - T\Phi = 0$.

### The metamerism theorem

**Two spectra look identical if and only if their difference lies in $\ker T$.**

$$T\Phi_1 = T\Phi_2 \iff T\Phi_1 - T\Phi_2 = 0 \iff T(\Phi_1 - \Phi_2) = 0 \iff \Phi_1 - \Phi_2 \in \ker T$$

The only property used is **linearity** — which is exactly what Grassmann's laws (1.4) assert empirically. Such a pair is a **metameric pair**; the difference is a **metameric black**.

### The premise doing quiet work

The step from "same $(L,M,S)$" to "looks the same" is **physiological, not mathematical**. It requires that the three cone responses are the *only* information the visual system receives about the spectrum at that point — opponent processing, adaptation, and everything cortical are functions of $(L,M,S)$, so if the triples match, nothing downstream can pull them apart. No side channel.

Excellent approximation, not exact:

- **Rods.** At mesopic levels rods contribute, giving effectively a fourth receptor and therefore a *different* kernel. Metamers matched in daylight can visibly break at twilight.
- **Melanopsin.** ipRGCs respond around 480 nm, driving pupil size and circadian rhythm. They don't feed hue directly, but pupil changes alter retinal illuminance, which perturbs a match at the margins.
- **Conditions.** A match holds only at the same retinal location, the same field size (hence the 2° and 10° observers), and the same adaptation state.

### The geometry: color is a quotient

In $\mathbb{R}^{81}$:

- $\ker T$ is a 78-dimensional subspace through the origin.
- All spectra matching a given $\Phi$ form the **coset** $\Phi + \ker T$ — a parallel translate of the kernel.
- Space is foliated into these parallel sheets. Each sheet is one perceived color.
- The set of sheets *is* $\mathbb{R}^3$.

$$\boxed{\text{A color is not a spectrum. It is an equivalence class of spectra.}}$$

"Color space" is the quotient space, literally. Worth writing on page one of your notes.

### Metameric blacks must go negative

Suppose $B \in \ker T$ and $B \ne 0$. Then $\langle B, \bar{y}\rangle = 0$. But $\bar{y} = V(\lambda) > 0$ across the visible band, so if $B$ were nonnegative everywhere that inner product would be strictly positive. Contradiction.

**Every metameric black takes negative values somewhere.** No realizable light is a metameric black — they exist only as *differences* between realizable lights.

This makes finding real metamers harder than the dimension count suggests. Given realizable $\Phi_1 \ge 0$, the set of realizable matches is

$$(\Phi_1 + \ker T) \cap \{\Phi \ge 0\}$$

— a 78-dimensional convex polytope, but a **bounded** one whose size depends on how much headroom $\Phi_1$ has. A bright broad mid-gray can be pushed in many directions. A very dark or highly saturated spectrum sits near zero across most of the band and has nowhere to go negative.

That is the mathematical statement of a fact you'll meet constantly in Module 2: **saturated and dark colors are hard to reproduce** — not from gamut geometry alone, but because the metamer set you're allowed to search shrinks toward a point.

### Why any of this matters

This is not a curiosity. It is the entire reason display technology works. Your monitor cannot reproduce the spectrum of a lemon. It reproduces a metamer of it: three narrow-ish primaries whose weighted sum lands on the same coset. Every image you have ever seen on a screen exploits this.

**Consequences to internalize:**

- **Illuminant metameric failure.** Two objects match under D65 and differ under incandescent, because reflectance multiplies the illuminant *before* the projection: $T[\Phi_{illum} \cdot R(\lambda)]$. Change $\Phi_{illum}$ and the difference $R_1 - R_2$ rotates out of the kernel. This is why you take fabric samples to the window.
- **Observer metameric failure.** Cone fundamentals vary between individuals (macular pigment density, lens yellowing with age, polymorphism in the L opsin). Your kernel isn't quite mine.
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

### And neither is the wavelength range

It's tempting to say the 380–780 nm window is *the* band life must use. That overstates it. Separate the physics from the accident.

**What is genuinely constrained**, and would hold on any planet around any star:

- **Lower bound (~1 eV, λ > ~1240 nm).** Detecting low-energy photons requires a low activation barrier, and a low barrier is tripped by thermal fluctuation. You get dark noise indistinguishable from signal. This is measured, not speculative: rhodopsin thermally isomerizes roughly once per rod per several hundred seconds, and deep-sea fish with red-shifted pigments show correspondingly higher dark noise — the prediction Barlow made in the 1950s.
- **Upper bound (~3.5–4 eV, λ < ~350 nm).** Photon energy exceeds typical covalent bond energies; DNA absorbs strongly near 260 nm. Photodamage.

So physics carves out a window of roughly **310–1240 nm — about two octaves.**

**What is contingent.** Human vision occupies less than half of that window. Biology routinely goes further, using unrelated chemistries:

- Birds and many insects see down to 300–320 nm.
- Plants sense far-red at ~730 nm via phytochromes (bilin chromophore, not retinal).
- Cryptochromes do blue/UV sensing with flavins.
- Pit vipers detect 5–30 μm infrared — but through TRPA1 thermal channels. That's heat sensing, not photochemistry, and it's correspondingly slow and coarse.

**Around a different star you should expect a different answer.** An M dwarf at ~3000 K peaks (per wavelength) near 966 nm; vision there would plausibly tune to 700–1100 nm, still inside the physics window but at its far end. Photosynthetic analogs would face a real problem — less energy per photon means multi-photon schemes to drive the same reactions — and the "red edge" biosignature astronomers search for would shift. Around a hotter F-type star you'd expect vision extending into the UV, paired with much heavier UV screening.

**The defensible claim:** physics sets a window a couple of octaves wide; the star determines where in that window the photons actually are; the atmosphere and the solvent filter further; evolution lands somewhere in the intersection. Water's transparency minimum near 400–500 nm is a strong constraint *for water-based life that evolved in an ocean* — which is itself contingent on water being the solvent, not a universal law.

Same lesson as trichromacy, one level down. Our color space is a projection of a slice, and both the projection and the slice could have been otherwise.

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

# --- Wyszecki decomposition: split any spectrum into visible + invisible ---
P = T.T @ np.linalg.inv(T @ T.T) @ T     # projector onto row space, rank 3
Q = np.eye(81) - P                       # projector onto ker T, rank 78

fundamental = P @ base
black       = Q @ base
assert np.allclose(fundamental + black, base)
assert np.allclose(T @ black, 0)
assert np.allclose(T @ fundamental, T @ base)   # color lives entirely here
# Plot both parts. `fundamental` is smooth; `black` oscillates around zero.

# --- Rank is invariant, nullity is not ---
for step in (1.0, 5.0, 10.0):
    Ts = build_T(step)
    print(step, Ts.shape[1], np.linalg.matrix_rank(Ts))   # rank stays 3
```

If you plot a metameric pair on the same axes and understand why they produce the same sensation, you have the central idea of this course.

---

## Exercises

**1.1** Load the Stockman–Sharpe fundamentals. Plot them. Confirm the L/M overlap visually and compute the correlation coefficient between $\bar{l}$ and $\bar{m}$ over the sampled range. (It's high — this is why the RG opponent channel is informative.)

**1.2** **Rank is invariant, nullity is not.** Build $T$ at 1 nm, 5 nm, and 10 nm sampling. Confirm `matrix_rank` returns 3 every time while the nullity moves (398, 78, 38). Then note the ratio of the third singular value to the first — this quantifies how thin the S-cone direction is, and hence how ill-conditioned the "three dimensions" really are.

**1.2b** **Decomposition.** Build the projectors $P$ and $Q = I - P$. Split a smooth reflectance into fundamental and metameric-black parts and plot both. Add the black part back at amplitudes $0, 0.5, 1, 2$ and confirm the XYZ never budges. Then check where $\Phi + \alpha B$ first goes negative — that's the boundary of the realizable metamer polytope.

**1.3** Generate a metameric pair as in the code above. Then generate a *physically realizable* one: find nonnegative $\Phi_1 \ne \Phi_2$ with $T\Phi_1 = T\Phi_2$, using constrained optimization. Note how much harder the nonnegativity constraint makes it — and that this constraint is exactly what a display's primaries face.

**1.3b** **The polytope shrinks.** Take three reflectances: a mid-gray (~0.5 flat), a very dark one (~0.03 flat), and a saturated one (near zero outside a narrow band). For each, measure the volume of realizable metamers by sampling: draw random $B \in \ker T$, find the largest $\alpha$ with $\Phi + \alpha B \ge 0$, and average. Confirm the mid-gray has far more room. You have just quantified why saturated and dark colors are hard to reproduce.

**1.4** Simulate dichromacy. Drop the M row from $T$, then reconstruct: find, for each input color, the nearest color in the space spanned by the remaining two fundamentals. Render an image through it. Compare with published Brettel–Viénot–Mollon simulations and note where yours diverges.

**1.5** Take a Macbeth ColorChecker's published reflectance spectra. Project them under D65 and under Illuminant A. Find the pair of patches whose LMS distance changes most between the two illuminants — you've found a metameric-failure-prone pair.

**1.6** Implement Stevens' law with $a = 0.4$ and plot it against a $\log$ curve and against $x^{1/2.2}$ over $[0.001, 1]$. Where do they agree? Where does the choice matter for an 8-bit encoding?

**1.7** **Units check.** Download cone fundamentals in both energy and quantal units. Confirm they differ by a factor proportional to $\lambda$. Project the same SPD through both and compare the resulting chromaticities — this is the bug from Module 0.6, made visible.

**1.8** Overlay the human photopic $V(\lambda)$, scotopic $V'(\lambda)$, and rhodopsin's measured absorption spectrum. Confirm $V'$ and rhodopsin coincide. Then explain the Purkinje shift purely in terms of which pigment is doing the work.

**1.9** **Alien colorimetry.** Compute a 3000 K M-dwarf blackbody. Construct three hypothetical cone fundamentals as Gaussians tuned to its per-photon peak, spaced like ours in relative terms. Build the analogous $T$ operator, generate a chromaticity diagram for that observer, and note what changes and what doesn't. (The horseshoe shape and the convexity survive; the wavelength labels don't.)

---

## Checkpoint

- Why can three primaries reproduce (most) colors, when light has infinite degrees of freedom?
- Why is the "78" in this module not a real number, and what is?
- What, precisely, is a metameric black, and why can't you buy a flashlight that emits one?
- What step in the metamerism proof is mathematics, and what step is physiology?
- Why do two shirts match in the store and clash outside?
- Why is there no such color as reddish-green?
- Why does gamma encoding exist? (Hint: the answer is not "CRTs.")
- Why are the L and M cone curves so close together?
- Why does dark adaptation take twenty minutes rather than twenty milliseconds?
- What sets the ~310–1240 nm window, and what doesn't it determine?

← [Module 0: Radiometry](00-radiometry.md) | → [Module 2: Colorimetry](02-colorimetry.md)
