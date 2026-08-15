"""
Generate every static figure used in the course docs.

    python make_figures.py

Writes SVG (line plots, scale-free) and PNG (pixel-exact colour) into figures/.
Figures needing CIE data look for data/*.csv and skip with a warning if absent.

Design notes:
  - SVGs are transparent with neutral #808080 axes so they read on light or dark.
  - Colour-critical figures are PNG at exact pixel values, never JPEG, and must
    be displayed at 1:1 or the artefact being demonstrated becomes a lie about
    the renderer's resampling rather than about the signal.
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
os.makedirs(OUT, exist_ok=True)

NEUTRAL = "#808080"
plt.rcParams.update({
    "figure.facecolor": "none", "axes.facecolor": "none", "savefig.facecolor": "none",
    "text.color": NEUTRAL, "axes.labelcolor": NEUTRAL, "axes.edgecolor": NEUTRAL,
    "xtick.color": NEUTRAL, "ytick.color": NEUTRAL, "grid.color": NEUTRAL,
    "font.size": 9, "axes.titlesize": 10, "axes.spines.top": False,
    "axes.spines.right": False, "grid.alpha": 0.25, "lines.linewidth": 1.6,
})

# --------------------------------------------------------------------------
# Colour conversion (Modules 2-4). Pure constants, no external data needed.
# --------------------------------------------------------------------------

def srgb_to_linear(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=float), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)

M_LIN_TO_LMS = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005]])

M_LMS_TO_LAB = np.array([
    [0.2104542553,  0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050,  0.4505937099],
    [0.0259040371,  0.7827717662, -0.8086757660]])

def linear_to_oklab(rgb):
    lms = rgb @ M_LIN_TO_LMS.T
    return np.cbrt(np.maximum(lms, 0.0)) @ M_LMS_TO_LAB.T

def oklab_to_linear(lab):
    lms_ = lab @ np.linalg.inv(M_LMS_TO_LAB).T
    return (lms_ ** 3) @ np.linalg.inv(M_LIN_TO_LMS).T

LUMA = np.array([0.2126729, 0.7151522, 0.0721750])


# --------------------------------------------------------------------------
# Figure 1 — sRGB transfer function and the code-allocation argument (Mod 5)
# --------------------------------------------------------------------------

def fig_transfer():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.2, 3.2))

    v = np.linspace(0, 1, 512)
    ax1.plot(v, srgb_to_linear(v), color="#7F77DD", label="sRGB EOTF (exact)")
    ax1.plot(v, v ** 2.2, color="#D85A30", ls="--", label=r"$x^{2.2}$")
    ax1.plot(v, v, color=NEUTRAL, lw=0.8, ls=":", label="linear (identity)")
    ax1.set_xlabel("code value"); ax1.set_ylabel("linear light")
    ax1.set_title("Decoding curve"); ax1.legend(frameon=False, fontsize=8)
    ax1.grid(True)

    codes = np.arange(1, 256)
    lin_step = np.full(255, 1 / 255)
    gam = srgb_to_linear(np.arange(256) / 255)
    gam_step = np.diff(gam)
    ax2.semilogy(codes, lin_step / gam[1:], color="#D85A30", label="linear 8-bit")
    ax2.semilogy(codes, gam_step / np.maximum(gam[1:], 1e-9), color="#7F77DD",
                 label="sRGB 8-bit")
    ax2.axhline(0.01, color=NEUTRAL, lw=0.8, ls=":")
    ax2.set_xlabel("code value"); ax2.set_ylabel("relative step  $\\Delta L / L$")
    ax2.set_title("Weber ratio per code step")
    ax2.legend(frameon=False, fontsize=8); ax2.grid(True, which="both")

    fig.tight_layout()
    fig.savefig(f"{OUT}/srgb-transfer.svg", transparent=True)
    plt.close(fig)
    print("  srgb-transfer.svg")


# --------------------------------------------------------------------------
# Figure 2 — the gradient triptych (Modules 3 and 4). PNG, pixel-exact.
# --------------------------------------------------------------------------

def fig_gradients():
    W, H, GAP = 720, 64, 10
    t = np.linspace(0, 1, W)[:, None]

    a_enc = np.array([1.0, 0.0, 0.0])
    b_enc = np.array([0.0, 1.0, 0.0])

    encoded = (1 - t) * a_enc + t * b_enc

    a_lin, b_lin = srgb_to_linear(a_enc), srgb_to_linear(b_enc)
    linear = linear_to_srgb((1 - t) * a_lin + t * b_lin)

    a_ok = linear_to_oklab(a_lin[None, :])[0]
    b_ok = linear_to_oklab(b_lin[None, :])[0]
    oklab = linear_to_srgb(np.clip(oklab_to_linear((1 - t) * a_ok + t * b_ok), 0, 1))

    bars = [encoded, linear, oklab]
    total_h = len(bars) * H + (len(bars) - 1) * GAP
    img = np.zeros((total_h, W, 4), dtype=np.uint8)
    for i, bar in enumerate(bars):
        y = i * (H + GAP)
        img[y:y + H, :, :3] = np.round(np.clip(bar, 0, 1) * 255).astype(np.uint8)[None, :, :]
        img[y:y + H, :, 3] = 255
    plt.imsave(f"{OUT}/gradient-triptych.png", img)
    print("  gradient-triptych.png  (display at 1:1)")

    fig, ax = plt.subplots(figsize=(8.2, 2.6))
    names = ["encoded sRGB", "linear light", "Oklab"]
    cols = ["#D85A30", "#EF9F27", "#7F77DD"]
    x = np.linspace(0, 1, W)
    for bar, n, c in zip(bars, names, cols):
        Y = srgb_to_linear(np.clip(bar, 0, 1)) @ LUMA
        ax.plot(x, Y, color=c, label=n)
    ax.set_xlabel("t"); ax.set_ylabel("relative luminance $Y$")
    ax.set_title("Luminance along a red-to-green interpolation")
    ax.legend(frameon=False, fontsize=8); ax.grid(True)
    fig.tight_layout()
    fig.savefig(f"{OUT}/gradient-luminance.svg", transparent=True)
    plt.close(fig)
    print("  gradient-luminance.svg")


# --------------------------------------------------------------------------
# Figure 3 — interpolation continuity (Module 7)
# --------------------------------------------------------------------------

def fig_smoothstep():
    t = np.linspace(0, 1, 1000)
    curves = {
        "linear":   (t, np.ones_like(t), np.zeros_like(t), "#888888"),
        "cubic":    (3 * t**2 - 2 * t**3, 6 * t - 6 * t**2, 6 - 12 * t, "#7F77DD"),
        "quintic":  (6 * t**5 - 15 * t**4 + 10 * t**3,
                     30 * t**4 - 60 * t**3 + 30 * t**2,
                     120 * t**3 - 180 * t**2 + 60 * t, "#1D9E75"),
    }
    fig, axes = plt.subplots(1, 3, figsize=(8.2, 2.7))
    titles = ["$S(t)$", "$S'(t)$", "$S''(t)$"]
    for i, (ax, title) in enumerate(zip(axes, titles)):
        for name, data in curves.items():
            ax.plot(t, data[i], color=data[3], label=name,
                    ls="--" if name == "linear" else "-",
                    lw=1.0 if name == "linear" else 1.6)
        ax.axhline(0, color=NEUTRAL, lw=0.6)
        ax.set_title(title); ax.set_xlabel("t"); ax.grid(True)
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{OUT}/smoothstep-continuity.svg", transparent=True)
    plt.close(fig)
    print("  smoothstep-continuity.svg")


# --------------------------------------------------------------------------
# Stubs — these need CIE tables in data/. See README.
# --------------------------------------------------------------------------

def fig_cone_fundamentals():
    if not os.path.exists("data/lms.csv"):
        print("  [skip] cone-fundamentals.svg - needs data/lms.csv from cvrl.org")
        return

def fig_chromaticity():
    if not os.path.exists("data/cie1931.csv"):
        print("  [skip] chromaticity-diagram.png - needs data/cie1931.csv")
        return

def fig_metamers():
    if not os.path.exists("data/cie1931.csv"):
        print("  [skip] metameric-pair.svg - needs data/cie1931.csv")
        return


if __name__ == "__main__":
    print(f"writing to {OUT}/")
    for f in (fig_transfer, fig_gradients, fig_smoothstep,
              fig_cone_fundamentals, fig_chromaticity, fig_metamers):
        f()
    print("done")
