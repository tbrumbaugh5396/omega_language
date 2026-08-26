"""Export the film's ingredient tessellations as web assets.

The carousel puts each SKU on the same pattern its segment uses in the hero
film, so the two pieces of the campaign read as one thing. Rather than
screenshot the video, the tiles are re-exported from the same generator that
drew them (assets/video/icons.py) — one definition of what a mango looks
like, so the storefront cannot drift from the film.

Motifs are exported white-on-transparent and the flat colour is applied in
CSS. That keeps one PNG per ingredient instead of one per colourway, and
lets a palette change happen in the stylesheet.

    python3 tools/make_patterns.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "assets" / "video"))

import icons                                              # noqa: E402

OUT = ROOT / "src" / "storefront" / "frontend" / "hero" / "patterns"
W = (255, 255, 255)

# Tile size is a compromise: large enough that the repeat is not obvious on a
# wide slide, small enough to stay a few KB. Alpha matches the film's `dim`.
TILES = {
    "mango": lambda: icons.tile_scatter(
        lambda s: icons.mango(s, W + (160,), W + (255,)), 340, dim=0.21),
    "passionfruit": lambda: icons.tile_scatter(
        lambda s: icons.passionfruit(s, W + (95,), W + (135,), W + (255,)),
        340, dim=0.23),
    "lavender": lambda: icons.tile_scatter(
        lambda s: icons.lavender(s, W + (130,), W + (245,)), 340, dim=0.21),
    "honey": lambda: icons.tile_honeycomb(82, W + (255,), W + (55,), 4.0,
                                          dim=0.17),
}


def mixed():
    """The multipack gets all four, since that is what is in the box."""
    from PIL import Image
    t = Image.new("RGBA", (620, 620), (0, 0, 0, 0))
    motifs = [icons.mango(190, W + (160,), W + (255,)),
              icons.passionfruit(170, W + (95,), W + (135,), W + (255,)),
              icons.lavender(195, W + (130,), W + (245,)),
              icons.hexagon(66, W + (255,), 4.0, W + (55,))]
    for m, (fx, fy, rot) in zip(motifs, [(0.24, 0.23, -12), (0.75, 0.28, 11),
                                         (0.26, 0.76, 9), (0.77, 0.78, -15)]):
        icons.stamp(t, icons._alpha(icons._rot(m, rot), 0.21), 620 * fx,
                    620 * fy)
    return t


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in list(TILES.items()) + [("all", mixed)]:
        tile = build()
        path = OUT / f"{name}.png"
        tile.save(path, optimize=True)
        print(f"  {name:<13} {tile.size[0]}x{tile.size[1]}  "
              f"{path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
