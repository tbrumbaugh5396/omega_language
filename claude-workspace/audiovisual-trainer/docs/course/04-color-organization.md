# Module 4 — Color Organization: Making the Space Navigable

**Goal:** understand the cylindrical reparameterizations of color, why HSV lies to you, and why Oklab/Oklch is the one you should actually put in your shaders.

---

## 4.1 The problem

XYZ and linear RGB are correct but unusable by hand. Nobody thinks "I want a bit more Z." Humans navigate color along three intuitive axes: how light, how vivid, what family. Every organization system is an attempt to build coordinates matching those intuitions.

The three axes recur under different names:

| Intuition | Munsell | HSV/HSL | CIELAB / Oklab |
|---|---|---|---|
| Which family | Hue | Hue | $h$ (hue angle) |
| How vivid | Chroma | Saturation | $C$ (chroma) |
| How light | Value | Value / Lightness | $L^*$ |

The systems differ entirely in whether the *spacing* along those axes is perceptually meaningful.

---

## 4.2 Munsell: measured, not computed

Albert Munsell (1905) built his system empirically — human observers judged equal perceptual steps, and the resulting solid is **irregular**. Its boundary bulges where high-chroma pigments exist (yellows reach high chroma only at high value; blues only at low value) and pinches where they don't.

Notation: `5R 4/14` = hue 5R, value 4, chroma 14.

The lesson is structural: **the perceptually uniform color solid is a lumpy asymmetric blob, not a cylinder, cone, or cube.** Any system that gives you a nice regular shape has bought that regularity by distorting perceptual spacing somewhere.

NCS (Natural Colour System) takes a different empirical tack, built on Hering's opponent pairs and describing colors by resemblance percentages to the six elementary colors. It's phenomenological rather than metric.

---

## 4.3 HSV and HSL: cheap, cylindrical, and lying

Both are direct reparameterizations of the **gamma-encoded RGB cube**. Let $M = \max(R,G,B)$, $m = \min(R,G,B)$, $C = M - m$.

**Hue** (both, identically) — angle around the cube's neutral diagonal:

$$H' = \begin{cases}
0 & C = 0 \\
\frac{G-B}{C} \bmod 6 & M = R \\
\frac{B-R}{C} + 2 & M = G \\
\frac{R-G}{C} + 4 & M = B
\end{cases}, \qquad H = 60° \cdot H'$$

**HSV:** $V = M$, $S_V = C/M$. The cube projected to a **cone**.
**HSL:** $L = (M+m)/2$, $S_L = C/(1 - |2L-1|)$. The cube projected to a **bicone**.

### What they get wrong

**They operate on encoded values.** The cube being reparameterized is not a linear-light space, so none of this has physical meaning either.

**"Value" and "Lightness" are not lightness.** $V = \max(R,G,B)$ ignores the luminance coefficients entirely. Compare at $V = 1.0$, $S = 1.0$:

| Color | sRGB | Relative luminance $Y$ | $L^*$ |
|---|---|---|---|
| Yellow | (1,1,0) | 0.928 | 97.1 |
| Cyan | (0,1,1) | 0.787 | 91.1 |
| Green | (0,1,0) | 0.715 | 87.8 |
| Magenta | (1,0,1) | 0.285 | 60.3 |
| Red | (1,0,0) | 0.213 | 53.2 |
| **Blue** | (0,0,1) | **0.072** | **32.3** |

Same "value." Yellow is nearly **13× more luminous than blue**. If you build a UI palette or a data-viz scale by holding V constant and sweeping H, you have built something that looks wildly uneven and is unreadable in grayscale.

**Hue is not perceptually uniform.** The 60° from red to yellow contains far more perceptual hue variation than the 60° from blue to magenta. Evenly-spaced HSV hues cluster perceptually.

**The Abney effect** — perceived hue shifts as you desaturate at constant HSV hue. HSV cannot represent this.

### When HSV is fine

Quick artist-facing controls where exactness doesn't matter; a "shift hue" slider; noise-driven variation where you just want *some* color spread. It's cheap and everyone knows it. Just never use it for anything requiring perceptual claims: palettes, colormaps, accessibility contrast, interpolation.

---

## 4.4 LCh: the cylindrical form of a perceptual space

Take CIELAB, convert the Cartesian $(a^*, b^*)$ opponent plane to polar:

$$C^* = \sqrt{a^{*2} + b^{*2}}, \qquad h = \operatorname{atan2}(b^*, a^*)$$

Now you have the same intuitive axes as HSL — but sitting on a perceptually-derived foundation. $L^*$ really is lightness; $C^*$ really is chroma; equal $\Delta h$ is roughly equal hue change.

**LCh solves the constant-lightness problem outright.** Sweep $h$ at fixed $L^*$ and $C^*$ and you get a palette of genuinely equal lightness. This is how good categorical palettes are built.

**Caveat:** at fixed $L^*$, achievable $C^*$ varies enormously with hue. Ask for $L^*=50, C^*=100$ at yellow and there is no such sRGB color. Perceptual palettes require gamut-aware chroma reduction — find max achievable chroma at each $(L, h)$ and take the minimum across your hue set.

**CIELAB's known flaw:** the blue region. Interpolating from blue toward white in CIELAB swings noticeably through purple. Which brings us to the fix.

---

## 4.5 Oklab: the one to use

Björn Ottosson, 2020. Same structure as CIELAB — a cone-like space, a cube-root compression, a linear map to opponent channels — but with the matrices fit to modern perceptual datasets, specifically optimizing for **hue constancy under lightness and chroma changes**. It fixes the blue-purple problem, and it's cheap: two 3×3 matrices and a cube root.

**Forward, from linear sRGB:**

$$\begin{bmatrix} l \\ m \\ s \end{bmatrix} =
\begin{bmatrix}
0.4122214708 & 0.5363325363 & 0.0514459929 \\
0.2119034982 & 0.6806995451 & 0.1073969566 \\
0.0883024619 & 0.2817188376 & 0.6299787005
\end{bmatrix}
\begin{bmatrix} R \\ G \\ B \end{bmatrix}_{linear}$$

$$l' = \sqrt[3]{l}, \quad m' = \sqrt[3]{m}, \quad s' = \sqrt[3]{s}$$

$$\begin{bmatrix} L \\ a \\ b \end{bmatrix} =
\begin{bmatrix}
0.2104542553 & 0.7936177850 & -0.0040720468 \\
1.9779984951 & -2.4285922050 & 0.4505937099 \\
0.0259040371 & 0.7827717662 & -0.8086757660
\end{bmatrix}
\begin{bmatrix} l' \\ m' \\ s' \end{bmatrix}$$

$L \in [0,1]$ (not 0–100 like CIELAB). Note the **cube root is applied to signed values** — use `sign(x)*pow(abs(x), 1/3)` if inputs may go negative (they can, in wide-gamut working spaces).

```glsl
vec3 linear_srgb_to_oklab(vec3 c) {
    float l = 0.4122214708*c.r + 0.5363325363*c.g + 0.0514459929*c.b;
    float m = 0.2119034982*c.r + 0.6806995451*c.g + 0.1073969566*c.b;
    float s = 0.0883024619*c.r + 0.2817188376*c.g + 0.6299787005*c.b;

    vec3 lms_ = pow(max(vec3(l, m, s), 0.0), vec3(1.0/3.0));

    return vec3(
        0.2104542553*lms_.x + 0.7936177850*lms_.y - 0.0040720468*lms_.z,
        1.9779984951*lms_.x - 2.4285922050*lms_.y + 0.4505937099*lms_.z,
        0.0259040371*lms_.x + 0.7827717662*lms_.y - 0.8086757660*lms_.z);
}

vec3 oklab_to_linear_srgb(vec3 lab) {
    float l_ = lab.x + 0.3963377774*lab.y + 0.2158037573*lab.z;
    float m_ = lab.x - 0.1055613458*lab.y - 0.0638541728*lab.z;
    float s_ = lab.x - 0.0894841775*lab.y - 1.2914855480*lab.z;

    vec3 lms = vec3(l_*l_*l_, m_*m_*m_, s_*s_*s_);

    return vec3(
        +4.0767416621*lms.x - 3.3077115913*lms.y + 0.2309699292*lms.z,
        -1.2684380046*lms.x + 2.6097574011*lms.y - 0.3413193965*lms.z,
        -0.0041960863*lms.x - 0.7034186147*lms.y + 1.7076147010*lms.z);
}
```

**Oklch** is the polar form, exactly as LCh is to Lab:

```glsl
vec3 oklab_to_oklch(vec3 lab) {
    return vec3(lab.x, length(lab.yz), atan(lab.z, lab.y));
}
vec3 oklch_to_oklab(vec3 lch) {
    return vec3(lch.x, lch.y * cos(lch.z), lch.y * sin(lch.z));
}
```

**Correct hue interpolation** takes the shorter arc:

```glsl
float lerp_hue(float h0, float h1, float t) {
    float d = mod(h1 - h0 + PI, TAU) - PI;   // shortest signed arc
    return h0 + d * t;
}
```

Interpolating in Oklab (Cartesian) gives smooth gradients with correct lightness. Interpolating in Oklch (polar) additionally preserves saturation through the middle — use Oklch when you want the midpoint to stay vivid, Oklab when you want it to pass naturally through neutral.

**Oklab is now in CSS Color 4** (`oklch()`, `color-mix(in oklch, ...)`), so this isn't niche — it's becoming the platform default.

---

## 4.6 Harmony as geometry

Classical schemes are hue-circle relationships:

| Scheme | Hue offsets |
|---|---|
| Complementary | $h, h+180°$ |
| Split-complementary | $h, h+150°, h+210°$ |
| Triadic | $h, h+120°, h+240°$ |
| Tetradic | $h, h+90°, h+180°, h+270°$ |
| Analogous | $h, h\pm30°$ |

These are only meaningful on a **perceptually uniform hue circle**. Applied to HSV, "complementary" often isn't, because HSV's 180° isn't a perceptual opposite.

Practical construction, all in Oklch:

- **Categorical palette** (distinguishable, equal weight): fix $L$ and $C$, distribute $h$ evenly. Reduce $C$ to the minimum achievable across all chosen hues so nothing clips.
- **Sequential colormap** (ordered data): monotonic $L$ from dark to light, $h$ varying slowly or fixed. Monotonic lightness is what makes it readable in grayscale and to colorblind viewers.
- **Diverging colormap** (signed data): two hues, $L$ peaking at the neutral midpoint, symmetric.
- **Tints/shades/tones:** tint = raise $L$; shade = lower $L$; tone = lower $C$. In Oklch these do what the words mean.

**Why viridis exists.** The classic "jet" rainbow colormap has non-monotonic lightness — it has bright bands at cyan and yellow that create false visual edges in data that has none, and it collapses under grayscale printing and under deuteranopia. Viridis was constructed with monotonic lightness in a perceptual space precisely to fix this. Once you've built module 4 you can construct your own.

---

## 4.7 Accessibility, briefly

~8% of men and ~0.5% of women have some form of color vision deficiency; deuteranomaly is by far the most common. Design rules that follow directly from the math:

- **Never encode information in hue alone.** Add shape, position, texture, or label.
- **Vary lightness** across categories — a lightness difference survives every form of CVD.
- **Avoid red/green as a semantic pair.** Blue/orange is the safe high-contrast axis, because it lies along the tritan-preserved direction.
- **WCAG contrast** uses a relative-luminance formula that decodes sRGB and applies the $(0.2126, 0.7152, 0.0722)$ coefficients from Module 2.5 — it's a luminance ratio, not a color-difference metric, and it is a crude one. APCA (in development for WCAG 3) models polarity and font weight and is substantially better.

Simulate CVD using the Brettel–Viénot–Mollon method: project LMS onto the plane spanned by the two surviving cone axes and the neutral/anchor directions. Run every palette through it.

---

## Exercises

**4.1** Build the table from 4.3 yourself: for the six saturated hues at $V=1$, compute $Y$ and $L^*$. Render them as swatches at "constant value" and observe the disaster. Then render at constant Oklab $L$ and compare.

**4.2** Implement Oklab/Oklch in GLSL. Verify round-trip accuracy to within float precision. Verify that pure sRGB white maps to $L = 1$.

**4.3** **Gradient comparison shader.** One fragment shader, five horizontal bands: interpolation in encoded sRGB, linear sRGB, CIELAB, Oklab, Oklch. Test with blue→white (exposes CIELAB's purple shift), red→green (exposes encoded sRGB's dark band), and blue→yellow (exposes gray-mud in linear).

**4.4** **Max chroma finder.** For a given $(L, h)$ in Oklch, binary-search the largest $C$ that stays in sRGB. Use it to render the sRGB gamut boundary as a function of hue at several lightnesses. This surface is the modern equivalent of the Munsell solid's irregular shape — plot it and see the bulge at yellow.

**4.5** Generate a categorical palette of 8 colors with equal Oklab lightness and maximal common chroma. Run it through a CVD simulator for protanopia, deuteranopia, and tritanopia. Iterate until all 8 remain distinguishable under all three.

**4.6** Reimplement viridis from scratch: define a monotonic $L$ ramp and a hue path in Oklch, sample it, and compare against the published viridis values. Then do the same for a rainbow map and plot both lightness profiles to show why one works.

**4.7** Implement the Abney effect demo: a set of swatches at constant Oklch hue with decreasing chroma, next to the same at constant HSV hue. Note which one holds its hue.

---

## Checkpoint

- Why does an HSV palette at constant V look uneven?
- What does "chroma" mean that "saturation" doesn't?
- Why is CIELAB bad at blue and Oklab better?
- Why does viridis work and jet doesn't?
- Why can't you pick an arbitrary $(L, C, h)$ and expect an sRGB color?

← [Module 3: Additive & Subtractive](03-additive-subtractive.md) | → [Module 5: Display](05-display.md)
