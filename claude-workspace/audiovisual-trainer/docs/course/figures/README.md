# EM radiation & human colour vision — figure assets

Two figures, each in light and dark themes, as SVG (vector, editable) and PNG (2040×1350 / 2040×1485, 3× scale).

## Figures

**`em-plane-wave-*`** — Contrasts the textbook sine-curve drawing of a plane wave (a *graph* of field strength vs. position) with what the field actually looks like in space: parallel sheets of uniform field, flipping direction every half wavelength. Corrects the common "wiggly rope" misreading.

**`cone-metamerism-*`** — The three human cone sensitivity curves (S/M/L), broad and heavily overlapping, and the metamerism that follows: two completely different spectra producing an identical triple of cone responses. The basis for why RGB displays work at all.

## Notes for reuse

- SVGs are self-contained: no external CSS, no `context-stroke` markers, no web fonts. Arrowheads are explicit paths, so they render identically in browsers, Illustrator, Figma, Inkscape, and rasterisers.
- Text uses a generic sans stack (`DejaVu Sans, Helvetica Neue, Helvetica, Arial, sans-serif`). Convert text to outlines if you need byte-identical rendering on machines without those fonts.
- Colours are hardcoded hex, deliberately — nothing auto-inverts. Use the matching theme file for your background rather than filtering.
- Cone sensitivity curves are schematic quadratic approximations for teaching, not fitted data. If you need quantitative accuracy, substitute the Stockman & Sharpe 2-deg cone fundamentals (CIE 170-1:2006).
- Regenerate or restyle both figures with `build_assets.py` — themes are a dict at the top.
