# Module 0 — Radiometry: Light as a Measurable Quantity

**Goal:** replace the word "brightness" with four precisely defined quantities, and understand why exactly one of them is what rendering computes.

---

## 0.1 Light is a function, not a triple

The physical ground truth of a beam of light is its **spectral power distribution**:

$$\Phi(\lambda), \qquad \lambda \in [380, 780]\ \text{nm}$$

This is a real-valued function on an interval. It lives in an infinite-dimensional function space. Every RGB triple you have ever written is a *projection* of such a function onto three axes — and the projection throws away almost everything.

Hold onto this. Module 1 is entirely about the structure of that projection.

Common SPD shapes worth being able to sketch from memory:

- **Blackbody / incandescent** — smooth, broad, rising toward red. Planck's law.
- **Daylight (D65)** — broad with characteristic Fraunhofer dips.
- **Fluorescent / cheap LED** — spiky. A few narrow emission lines pretending to be white.
- **Laser** — a delta function.

The spiky ones are why two lights that look identical under one illuminant look different under another. That phenomenon has a name and a linear-algebraic explanation, both in Module 1.

---

## 0.2 The four quantities

Build them in order. Each one is a derivative of the previous with respect to a new variable.

### Radiant flux, $\Phi$ — watts

Total energy per unit time crossing a surface or leaving a source. A 100 W bulb emits some fraction of 100 W as radiant flux. That's it. No direction, no area.

### Irradiance, $E$ — W·m⁻²

Flux per unit area *arriving* at a surface:

$$E = \frac{d\Phi}{dA}$$

The outgoing version is **radiant exitance** $M$, same units, different direction of travel. Keeping them named separately saves you from sign errors later.

### Radiant intensity, $I$ — W·sr⁻¹

Flux per unit **solid angle**, for point sources:

$$I = \frac{d\Phi}{d\omega}$$

### Radiance, $L$ — W·m⁻²·sr⁻¹

Flux per unit solid angle per unit **projected** area:

$$L = \frac{d^2\Phi}{dA^{\perp}\,d\omega} = \frac{d^2\Phi}{\cos\theta\, dA\, d\omega}$$

**This is the one rendering computes.** Every ray you trace, every fragment you shade, is ultimately answering: what is the radiance arriving along this ray?

---

## 0.3 Solid angle

A solid angle is the 2D generalization of an angle. An angle is arc length on the unit circle; a solid angle is area on the unit sphere.

$$\omega = \frac{A}{r^2} \quad \text{steradians}$$

The full sphere is $4\pi$ sr; a hemisphere is $2\pi$ sr.

In spherical coordinates, the differential element is:

$$d\omega = \sin\theta\, d\theta\, d\phi$$

That $\sin\theta$ is not decoration — it is the Jacobian of the spherical parameterization. Forgetting it is the single most common bug in hemisphere integration, and it produces results biased toward the pole.

**Sanity check the hemisphere:**

$$\int_{H^2} d\omega = \int_0^{2\pi}\!\!\int_0^{\pi/2} \sin\theta\, d\theta\, d\phi = 2\pi \cdot [-\cos\theta]_0^{\pi/2} = 2\pi$$

**Now the one that actually matters** — the cosine-weighted (projected) solid angle:

$$\int_{H^2} \cos\theta\, d\omega = \int_0^{2\pi}\!\!\int_0^{\pi/2} \cos\theta\sin\theta\, d\theta\, d\phi = 2\pi \cdot \tfrac{1}{2} = \pi$$

**That $\pi$ is why Lambertian BRDFs have a $1/\pi$ in them.** If a surface reflects fraction $\rho$ of incoming energy and scatters it uniformly, then $f_r = \rho/\pi$ — the $\pi$ normalizes the cosine-weighted integral back to 1. If you have ever wondered where that constant came from and just accepted it, this is the derivation.

---

## 0.4 Why radiance is the privileged quantity

Two properties, both load-bearing:

**1. Radiance is invariant along a ray in vacuum.** $L$ does not fall off with distance. The inverse-square law applies to *irradiance*, not radiance, and it arises purely because the solid angle subtended by a source shrinks as $1/r^2$. This is why a wall doesn't look dimmer when you step back from it, and why a camera's exposure depends on aperture and not on subject distance.

**2. Radiance is what sensors respond to.** A pixel integrates radiance over its solid angle and area. Cones do the same. So "what color is this pixel" reduces to "what is the radiance along these rays."

Everything else is derived. Irradiance is radiance integrated over the hemisphere with a cosine:

$$E = \int_{H^2} L(\omega)\cos\theta\, d\omega$$

---

## 0.5 Lambert's cosine law is geometry, not physics

A common misreading: "Lambertian surfaces reflect light proportional to $\cos\theta$ because of how the material works."

No. The $\cos\theta$ comes from **projected area**. A beam of cross-section $dA^\perp$ striking a surface at angle $\theta$ spreads across surface area $dA = dA^\perp / \cos\theta$. Same energy, more area, so less energy per unit area. The material is not involved.

This is why the cosine term belongs to the *rendering equation*, not to the BRDF — it's in the integrand for every material, diffuse or not.

---

## 0.6 Spectral radiance and the collapse

Every quantity above has a spectral version, denoted with a $\lambda$ subscript:

$$L_\lambda(\lambda) \quad \text{in}\ \ \text{W·m}^{-2}\text{·sr}^{-1}\text{·nm}^{-1}$$

and the non-spectral version is the integral over wavelength.

**Real renderers cheat here.** Instead of tracking $L_\lambda$ as a function, they track three numbers and pretend light transport is separable across R, G, B. This is wrong. It's wrong in a way that shows up specifically in:

- Dispersion (prisms, chromatic aberration in lenses)
- Fluorescence
- Thin-film interference (soap bubbles, oil slicks, beetle shells)
- Multiple scattering through strongly-colored media

Spectral renderers keep the full function. Know that the cheat exists, know what it costs, and then use it anyway most of the time.

---

## 0.7 Photometry: radiometry weighted by the eye

Photometry is radiometry with one modification: weight the spectrum by the **luminous efficiency function** $V(\lambda)$ before integrating.

$$\Phi_v = K_m \int \Phi_\lambda(\lambda)\, V(\lambda)\, d\lambda, \qquad K_m = 683\ \text{lm/W}$$

$V(\lambda)$ is the photopic (cone-driven, daylight) sensitivity curve, peaking at **555 nm**. The scotopic (rod-driven, night) curve $V'(\lambda)$ peaks at **507 nm** with $K'_m = 1700$ lm/W. The shift between them is the **Purkinje effect** — why red flowers go black at dusk while blue ones stay bright.

The correspondence table is exact and worth memorizing:

| Radiometric | Photometric | Unit |
|---|---|---|
| Radiant flux $\Phi$ | Luminous flux | lumen (lm) |
| Irradiance $E$ | Illuminance | lux (lm/m²) |
| Radiant intensity $I$ | Luminous intensity | candela (cd = lm/sr) |
| **Radiance $L$** | **Luminance** | **nit (cd/m²)** |

**Nits are the unit your display is spec'd in.** A typical SDR monitor peaks near 100–300 nits; HDR displays claim 1000–4000. When Module 5 covers the PQ transfer function, it is defined in absolute nits — which is exactly why HDR grading is harder than SDR.

Useful anchors: overcast sky ≈ 2,000 nits, clear sky ≈ 8,000, sun's disk ≈ 1.6 × 10⁹, paper indoors ≈ 100.

Note the candela is an **SI base unit**. The system of physical units contains, at its foundation, a curve describing the average human eye. That's a strange and telling fact about this whole subject.

---

## Exercises

**0.1** Derive $\int_{H^2}\cos\theta\,d\omega = \pi$ by hand. Then compute it numerically with uniform random sampling on the hemisphere and confirm convergence to $\pi$.

**0.2** Write a Monte Carlo hemisphere integrator. Sample directions two ways: (a) uniformly over solid angle, (b) cosine-weighted. Integrate a constant function. Show (b) has lower variance and identify the PDF that makes the estimator unbiased in each case.

**0.3** Implement Planck's law:
$$B_\lambda(\lambda, T) = \frac{2hc^2}{\lambda^5}\frac{1}{e^{hc/\lambda k T} - 1}$$
Plot normalized SPDs for 1900 K (candle), 2700 K (tungsten), 5500 K (daylight), 6500 K (D65-ish). Verify Wien's displacement law: $\lambda_{max} T \approx 2.898\times10^{-3}$ m·K. Save these — Module 2 turns them into chromaticity coordinates and traces the Planckian locus.

**0.4** A 1 m² Lambertian panel emits 100 W uniformly over the hemisphere. Compute its radiant exitance, and its radiance. (Answer: $M = 100$ W/m², $L = 100/\pi \approx 31.8$ W·m⁻²·sr⁻¹. Make sure you understand where the $\pi$ came from.)

**0.5** Download $V(\lambda)$. Compute the luminous efficacy (lm/W) of: an ideal 555 nm monochromatic source, a 2700 K blackbody, and an equal-energy white. Explain why LED efficiency claims tend to quote green-heavy spectra.

---

## Checkpoint

Before moving on, you should be able to answer without looking:

- Why doesn't a wall get dimmer as you walk away from it?
- Where does the $1/\pi$ in a Lambertian BRDF come from?
- What is the difference between a lumen and a watt?
- Why is $\sin\theta$ in the solid angle element?

→ [Module 1: The Eye](01-the-eye.md)
