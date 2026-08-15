# Module 6 — The GPU Pipeline: How Triangles Become Fragments

**Goal:** be able to write a software rasterizer, and understand every stage of the hardware pipeline as a specific piece of mathematics rather than a black box.

---

## 6.1 Homogeneous coordinates

A point in 3D becomes $(x, y, z, w)$ with $w \ne 0$, and $(x,y,z,w) \sim (\alpha x, \alpha y, \alpha z, \alpha w)$ — equivalence classes under scaling, i.e. **rays through the origin in $\mathbb{R}^4$**. This is $\mathbb{P}^3$.

**Exactly the same construction as chromaticity in Module 2.3.** There, an intensity ray in XYZ collapsed to a chroma point. Here, a ray in $\mathbb{R}^4$ collapses to a point in 3-space. Same projective geometry, different application. If you understood one, you understand the other.

Two payoffs:

**1. Translation becomes linear.** In 3D it's affine and can't be a 3×3 matrix. In 4D:

$$\begin{bmatrix}1&0&0&t_x\\0&1&0&t_y\\0&0&1&t_z\\0&0&0&1\end{bmatrix}$$

So the whole chain — model, view, projection — composes into one matrix multiply.

**2. Points at infinity exist.** $w = 0$ is a direction, not a location. Directional lights, vanishing points, and the horizon all become ordinary elements of the space instead of special cases.

**Normals do not transform by $M$.** They transform by $(M^{-1})^T$, because a normal is a covector — defined by the plane it's perpendicular to, not by a displacement. Under non-uniform scale, transforming a normal with $M$ tilts it wrong. For rotation-only matrices $(M^{-1})^T = M$, which is why the bug hides until someone scales an object non-uniformly.

---

## 6.2 The projection matrix

Perspective projection, standard OpenGL form (right-handed, NDC $z \in [-1,1]$):

$$P = \begin{bmatrix}
\frac{1}{a\tan(\theta/2)} & 0 & 0 & 0 \\
0 & \frac{1}{\tan(\theta/2)} & 0 & 0 \\
0 & 0 & \frac{f+n}{n-f} & \frac{2fn}{n-f} \\
0 & 0 & -1 & 0
\end{bmatrix}$$

**The whole trick is row 4:** it copies $-z_{eye}$ into $w_{clip}$. Then the perspective divide $(x/w, y/w, z/w)$ divides by depth, which is what makes distant things small. The projection matrix does not project; it *sets up* the divide.

**Depth is nonlinear.** After the divide, NDC $z$ is a function of $1/z_{eye}$. So depth precision is concentrated near the near plane. Setting near = 0.01 to "be safe" destroys far-field precision and produces z-fighting kilometers out. Better: push near as far as you can tolerate, or use a **reversed-Z** buffer (swap near/far, use `GL_GREATER`, clear to 0) with a float depth format — the float32 exponent distribution then cancels the projective distribution almost exactly, giving near-uniform relative precision. This is close to free and is the right default in new code.

**Clipping** happens in clip space, *before* the divide, against $-w \le x,y,z \le w$. Doing it before is essential: geometry behind the eye has $w < 0$, and dividing by a negative $w$ produces points that appear mirrored in front of you. Clipping against the near plane removes them first.

---

## 6.3 Rasterization: edge functions

Given a triangle in screen space, which pixels are inside? Pineda's answer (1988), and essentially what the hardware does.

For a directed edge from $\mathbf{a}$ to $\mathbf{b}$, define:

$$E_{ab}(\mathbf{p}) = (p_x - a_x)(b_y - a_y) - (p_y - a_y)(b_x - a_x)$$

This is the 2D cross product $(\mathbf{b}-\mathbf{a}) \times (\mathbf{p}-\mathbf{a})$ — a **signed area**, positive on one side of the line, negative on the other, zero on it.

A point is inside iff all three edge functions share a sign.

Two properties make this fast:

**It's linear in $\mathbf{p}$.** So $E(x+1, y) = E(x,y) + (b_y - a_y)$ — one add per pixel, all integer. Hardware rasterizers walk tiles this way.

**It computes barycentrics for free.** With the full triangle area $A = E_{ab}(\mathbf{c})$:

$$\lambda_0 = \frac{E_{bc}(\mathbf{p})}{A}, \quad \lambda_1 = \frac{E_{ca}(\mathbf{p})}{A}, \quad \lambda_2 = \frac{E_{ab}(\mathbf{p})}{A}, \qquad \sum\lambda_i = 1$$

**Fill rules.** Pixels exactly on a shared edge belong to exactly one triangle, or you get double-shading (visible with blending) or gaps. The **top-left rule** is the standard tiebreak: a pixel on an edge is in if that edge is a top or left edge of the triangle. Getting this wrong produces seams along every shared edge in your mesh.

```python
def edge(a, b, p):
    return (p[0]-a[0])*(b[1]-a[1]) - (p[1]-a[1])*(b[0]-a[0])

def raster(v0, v1, v2, width, height):
    area = edge(v0, v1, v2)
    if area == 0: return
    xmin, xmax = int(min(v0[0],v1[0],v2[0])), int(max(v0[0],v1[0],v2[0]))+1
    ymin, ymax = int(min(v0[1],v1[1],v2[1])), int(max(v0[1],v1[1],v2[1]))+1
    for y in range(max(0,ymin), min(height,ymax)):
        for x in range(max(0,xmin), min(width,xmax)):
            p = (x + 0.5, y + 0.5)          # sample at pixel CENTER
            w0, w1, w2 = edge(v1,v2,p), edge(v2,v0,p), edge(v0,v1,p)
            if (w0 >= 0 and w1 >= 0 and w2 >= 0) or \
               (w0 <= 0 and w1 <= 0 and w2 <= 0):
                yield x, y, (w0/area, w1/area, w2/area)
```

Note `+ 0.5`: you sample at pixel centers, because a pixel is a point sample (Module 5.1), and its center is where the sample sits.

---

## 6.4 Perspective-correct interpolation

Here is the thing that separates a working rasterizer from a broken one.

Screen-space barycentrics are **not** the object-space barycentrics. Perspective divide is nonlinear, so linear interpolation of a vertex attribute across the screen is wrong — the classic symptom is a texture on a floor that warps along the diagonal seam between the two triangles of a quad.

**What *is* linear in screen space is the attribute divided by $w$, and $1/w$ itself.** So:

$$\frac{1}{w} = \sum_i \lambda_i \frac{1}{w_i}, \qquad
\frac{A}{w} = \sum_i \lambda_i \frac{A_i}{w_i}, \qquad
A = \frac{A/w}{1/w}$$

```python
# at each vertex, precompute inverse w
iw = [1.0/v.w for v in verts]

# per fragment
one_over_w = l0*iw[0] + l1*iw[1] + l2*iw[2]
attr_over_w = l0*(a0*iw[0]) + l1*(a1*iw[1]) + l2*(a2*iw[2])
attr = attr_over_w / one_over_w
```

**Why is $1/w$ linear?** Because $w_{clip} = -z_{eye}$, planes in eye space map to planes in the $(x/z, y/z, 1/z)$ coordinates. The reciprocal of depth is affine in screen coordinates — a fact worth deriving once by hand.

In GLSL this is automatic for `smooth` varyings. The `noperspective` qualifier turns it off (correct for screen-space quantities), and `flat` skips interpolation entirely (mandatory for integers).

**And this closes the loop with Module 2.** Both chromaticity and perspective are divisions by a homogeneous coordinate, and both destroy the linearity of what came before. Interpolating in chromaticity space is wrong for the same reason interpolating screen-space UVs is wrong.

---

## 6.5 Depth, and the rest of the fixed function

**Z-buffer:** store $z$ per pixel, keep the nearest. Simple, and the reason you don't have to sort. Costs: transparency doesn't work (hence sorting, or OIT), and the nonlinear distribution causes z-fighting.

**Early-Z** rejects fragments before shading — a large win, but the driver disables it if the shader writes `gl_FragDepth` or uses `discard`, because then depth isn't known until after shading. This is a common accidental performance cliff: one `discard` for alpha-testing foliage can cost you early-Z on the whole pass.

**Blending** is fixed function, happens after the shader, and — per Module 3 — happens in whatever space your framebuffer is in. `GL_FRAMEBUFFER_SRGB` makes it happen in linear. Standard "over":

$$C_{out} = \alpha_s C_s + (1-\alpha_s) C_d$$

Premultiplied form ($C$ already scaled by $\alpha$) uses `ONE, ONE_MINUS_SRC_ALPHA` and is better behaved under filtering and compositing chains.

---

## 6.6 The execution model, and why shaders are weird

GPUs are wide SIMD. NVIDIA calls a group of 32 lanes a **warp**; AMD calls 64 (or 32) a **wavefront**. **All lanes execute the same instruction.**

**Branch divergence.** If lanes in a warp take different paths, the hardware executes *both* paths and masks off the inactive lanes. Cost = sum of both branches. So:

- A branch is free if the whole warp agrees (uniform branching on a uniform variable — genuinely free).
- A branch on per-pixel data can cost the sum of all taken paths.
- `discard` doesn't exit early; it masks the lane. The warp keeps running.

**Latency hiding, not caches.** CPUs use big caches and speculation to avoid stalls. GPUs use **massive occupancy** — when one warp stalls on a memory fetch, the scheduler swaps in another. This requires many warps resident, which requires each to use few registers. **High register usage → low occupancy → stalls are exposed.** This is why an inlined 400-line shader can be slower than a simpler one doing more work.

### The 2×2 quad, and where derivatives come from

Fragments are shaded in **2×2 quads**, always. Two consequences that explain a lot:

**1. `dFdx` / `dFdy` are finite differences across the quad.**

$$\text{dFdx}(f) \approx f(x+1,y) - f(x,y)$$

That's why they're nearly free — the neighbor's value is already in an adjacent lane. That's also why they're *inaccurate*: they're a 1-pixel forward difference, constant across the quad in the `coarse` variant. And it's why **they are undefined in non-uniform control flow** — if the neighbor lane took a different branch, its value is garbage. Never call `texture()` (which needs derivatives for mip selection) inside a divergent branch; compute the derivative outside, or use `textureLod`/`textureGrad`.

**2. Quad overshading.** A triangle covering one pixel still shades four fragments. Dense geometry with triangles smaller than 2×2 pixels can waste up to 4× your shading. This is a real cost of over-tessellation and a motivation for visibility buffers and mesh shaders.

`fwidth(f) = abs(dFdx(f)) + abs(dFdy(f))` — an estimate of how much $f$ changes per pixel. **This is the bridge to Module 7:** it's the filter width in Module 5's sampling theory, computed for free by the hardware, and it is what makes analytic antialiasing possible.

---

## 6.7 The whole pipeline

```
Vertex buffer
   ↓  Vertex shader        — model→world→view→clip. Your matrices.
Clip space (x,y,z,w)
   ↓  Clipping             — against -w ≤ xyz ≤ w, BEFORE divide
   ↓  Perspective divide   — /w. Projective geometry. Module 2's operation.
NDC [-1,1]³
   ↓  Viewport transform   — to pixels
Screen space
   ↓  Rasterization        — edge functions, barycentrics, fill rule
Fragments (in 2×2 quads)
   ↓  Early-Z              — unless you broke it
   ↓  Fragment shader      — SIMD, divergence-sensitive, derivatives available
   ↓  Depth/stencil test
   ↓  Blend                — in whatever space your FBO is
Framebuffer
```

---

## Exercises

**6.1** **Write the software rasterizer.** This is the centerpiece. ~200 lines, no dependencies beyond an array and a PNG writer. Requirements: edge functions, top-left fill rule, barycentric interpolation, a z-buffer, and perspective-correct UVs. Render a spinning textured cube.

**6.2** Deliberately break perspective correction in 6.1 — interpolate UVs linearly in screen space. Render a large ground quad in strong perspective. Photograph the diagonal seam. This is the bug you will now recognize instantly forever.

**6.3** Derive the OpenGL perspective matrix from scratch: start from similar triangles, $x_{screen} = x_{eye} \cdot d / (-z_{eye})$, and construct the matrix that produces this after the divide. Then derive the $z$ row from the constraint that $z_{eye}=n \mapsto -1$ and $z_{eye}=f \mapsto 1$.

**6.4** Plot NDC depth vs eye depth for $n$ = 0.01, 0.1, 1.0 with $f$ = 1000. Compute the number of distinct float32 depth values available in the far half of the frustum for each. Then implement reversed-Z and redo the count.

**6.5** Prove that $1/w$ is linear in screen space. (Hint: a plane in eye space is $ax+by+cz=d$; divide through by $z$ and substitute screen coordinates.)

**6.6** Implement MSAA in your software rasterizer: 4 coverage samples per pixel, one shading evaluation at the centroid. Compare against 4× supersampling in both quality and shading-invocation count. Then compare both against no AA on a near-horizontal edge.

**6.7** Write a GLSL shader with a divergent branch where one side does 100 iterations of noise and the other returns immediately, driven by `step(0.5, uv.x)`. Time it. Then drive the same branch by a uniform. Compare. You have just measured warp divergence.

**6.8** Write a shader that calls `texture()` inside an `if` on a per-pixel condition. Observe the artifacts along the boundary. Fix it with `textureGrad`. Explain what happened in terms of the 2×2 quad.

---

## Checkpoint

- What does the projection matrix actually do? (Not "project.")
- Why must clipping happen before the perspective divide?
- Why interpolate $u/w$ instead of $u$?
- Why do normals need $(M^{-1})^T$?
- Why is `dFdx` cheap, and why is it undefined in a divergent branch?
- What does a single `discard` cost you beyond the discarded fragment?

← [Module 5: Display](05-display.md) | → [Module 7: Shaders](07-shaders.md)
