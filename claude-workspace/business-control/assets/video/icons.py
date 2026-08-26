"""The four ingredient motifs, and the machinery that makes them tile.

Everything here draws with Pillow primitives rather than loading art, because
the pattern has to be generated at whatever size and colour a segment asks
for. A fixed PNG would either pixelate when scaled up or lock the palette.

Seamlessness is the whole point of a tessellation, and it is easy to get
subtly wrong: a motif that overhangs the tile edge leaves a visible seam
every tile width. So `stamp` draws each motif nine times, once per
neighbouring wrap position, and lets the clipping helper throw away what
falls outside. Whatever leaves the right edge re-enters on the left by
construction, not by eyeballing.
"""
import math

from PIL import Image, ImageDraw

SS = 3            # supersample factor; motifs are drawn big and shrunk so the
                  # curves come out smooth without any AA in ImageDraw itself


def blend(base, im, x, y):
    """alpha_composite that tolerates negative and off-canvas positions.

    Pillow's own alpha_composite refuses a negative destination, which is
    exactly the case a wrapping stamp needs most.
    """
    x, y = int(round(x)), int(round(y))
    bw, bh = base.size
    iw, ih = im.size
    sx, sy = max(0, -x), max(0, -y)
    ex, ey = min(iw, bw - x), min(ih, bh - y)
    if ex <= sx or ey <= sy:
        return
    base.alpha_composite(im.crop((sx, sy, ex, ey)), (x + sx, y + sy))


def stamp(tile, motif, cx, cy):
    """Place `motif` centred at (cx, cy) on `tile`, wrapping at every edge."""
    w, h = tile.size
    mw, mh = motif.size
    for dx in (-w, 0, w):
        for dy in (-h, 0, h):
            blend(tile, motif, cx - mw / 2 + dx, cy - mh / 2 + dy)


def _shrink(im):
    return im.resize((max(1, im.width // SS), max(1, im.height // SS)),
                     Image.LANCZOS)


def _rot(im, deg):
    return im.rotate(deg, resample=Image.BICUBIC, expand=True)


def _alpha(im, a):
    """Scale an image's alpha channel by `a` (0..1)."""
    if a >= 0.999:
        return im
    r, g, b, al = im.split()
    return Image.merge("RGBA", (r, g, b, al.point(lambda v: int(v * a))))


# ---------------------------------------------------------------- motifs ---

def mango(h, body, leaf):
    """A mango: rounder at the base, tapering to the stem, with one leaf."""
    W, H = int(h * 0.64 * SS), int(h * SS)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    a, b = W * 0.46, H * 0.37
    cx, cy = W * 0.50, H * 0.60
    pts = []
    for i in range(200):
        t = 2 * math.pi * i / 200
        # cos(t) is +1 at the top: widening below centre and stretching above
        # it is what separates a mango from a plain egg.
        x = cx + a * math.sin(t) * (1 - 0.13 * math.cos(t))
        y = cy - b * math.cos(t) * (1 + 0.16 * math.cos(t))
        pts.append((x, y))
    d.polygon(pts, fill=body)

    # leaf: a lens, two parabolic arcs back to back
    lw, lh = int(W * 0.86), int(H * 0.19)
    lf = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lf)
    top = [(u * lw, lh / 2 - (lh / 2) * (1 - (2 * u - 1) ** 2))
           for u in [i / 40 for i in range(41)]]
    bot = [(u * lw, lh / 2 + (lh / 2) * (1 - (2 * u - 1) ** 2))
           for u in [i / 40 for i in range(40, -1, -1)]]
    ld.polygon(top + bot, fill=leaf)
    lf = _rot(lf, 34)
    blend(im, lf, cx - lf.width * 0.82, cy - b * 1.04 - lf.height * 0.46)
    d.line([(cx - W * 0.02, cy - b * 1.00), (cx + W * 0.01, cy - b * 1.16)],
           fill=leaf, width=int(W * 0.035))
    return _shrink(im)


def passionfruit(h, rind, pulp, seed):
    """A halved passion fruit: rind, pulp, and a scatter of seeds."""
    S = int(h * SS)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c, R = S / 2, S * 0.46

    d.ellipse([c - R, c - R, c + R, c + R], fill=rind)
    d.ellipse([c - R * .80, c - R * .80, c + R * .80, c + R * .80],
              fill=pulp)
    d.ellipse([c - R * .70, c - R * .70, c + R * .70, c + R * .70],
              outline=rind, width=int(S * 0.016))

    for i in range(11):
        t = 2 * math.pi * i / 11 + 0.22
        rr = R * (0.30 if i % 3 == 0 else 0.50)
        sx, sy = c + rr * math.cos(t), c + rr * math.sin(t)
        sd = Image.new("RGBA", (int(S * 0.13), int(S * 0.09)), (0, 0, 0, 0))
        ImageDraw.Draw(sd).ellipse([0, 0, sd.width - 1, sd.height - 1],
                                   fill=seed)
        blend(im, _rot(sd, math.degrees(-t) + 90),
              sx - sd.width * .6, sy - sd.height * .6)

    d.ellipse([c - S * .035, c - R - S * .05, c + S * .035, c - R + S * .03],
              fill=rind)
    return _shrink(im)


def lavender(h, stem, bud):
    """A lavender sprig: paired buds up a spike, two leaves at the base."""
    W, H = int(h * 0.44 * SS), int(h * SS)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = W / 2

    d.line([(cx, H * 0.98), (cx, H * 0.42)], fill=stem,
           width=max(1, int(W * 0.055)))

    n = 7
    for i in range(n):
        f = i / (n - 1)                       # 0 at the base of the spike
        y = H * (0.52 - 0.46 * f)
        k = 1.0 - 0.62 * f                    # buds taper toward the tip
        bw, bh = W * 0.36 * k, W * 0.50 * k
        for side in (-1, 1):
            if i == n - 1 and side < 0:
                continue                      # single bud crowns the spike
            x = cx + side * W * 0.14 * k
            b = Image.new("RGBA", (max(2, int(bw)), max(2, int(bh))),
                          (0, 0, 0, 0))
            ImageDraw.Draw(b).ellipse([0, 0, b.width - 1, b.height - 1],
                                      fill=bud)
            blend(im, _rot(b, -side * 22), x - b.width / 2, y - b.height / 2)

    for side in (-1, 1):
        lf = Image.new("RGBA", (int(W * 0.50), int(W * 0.17)), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lf)
        top = [(u * lf.width, lf.height / 2
                - (lf.height / 2) * (1 - (2 * u - 1) ** 2))
               for u in [i / 30 for i in range(31)]]
        bot = [(u * lf.width, lf.height / 2
                + (lf.height / 2) * (1 - (2 * u - 1) ** 2))
               for u in [i / 30 for i in range(30, -1, -1)]]
        ld.polygon(top + bot, fill=stem)
        lf = _rot(lf, 26 * side if side > 0 else -26)
        if side < 0:
            lf = lf.transpose(Image.FLIP_LEFT_RIGHT)
        blend(im, lf, cx + (0 if side > 0 else -lf.width), H * 0.68)
    return _shrink(im)


def hexagon(R, outline, width, fill=None):
    """One flat-top hexagon — the cell the honeycomb grid repeats."""
    S = int(2 * R * SS) + 8
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = S / 2
    pts = [(c + R * SS * math.cos(math.pi / 3 * i),
            c + R * SS * math.sin(math.pi / 3 * i)) for i in range(6)]
    if fill:
        d.polygon(pts, fill=fill)
    d.line(pts + [pts[0]], fill=outline, width=int(width * SS), joint="curve")
    return _shrink(im)


# ----------------------------------------------------------------- tiles ---
# Each returns (tile_image, (tile_w, tile_h)). Sizes differ per motif: the
# honeycomb's period is fixed by hex geometry, the others are free.

def tile_scatter(draw_one, size, dim=1.0):
    """Four motifs in a half-drop arrangement — two large, two small."""
    tw = th = size
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    big = draw_one(size * 0.52)
    small = draw_one(size * 0.30)
    for cx, cy, m, rot in ((0.25, 0.26, big, -14), (0.75, 0.76, big, 166),
                           (0.76, 0.24, small, 38), (0.24, 0.74, small, 208)):
        stamp(tile, _alpha(_rot(m, rot), dim), tw * cx, th * cy)
    return tile


def tile_honeycomb(R, outline, fill, width=3.0, dim=1.0):
    tw, th = int(round(3 * R)), int(round(math.sqrt(3) * R))
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    cell = _alpha(hexagon(R, outline, width, fill), dim)
    stamp(tile, cell, 0, 0)
    stamp(tile, cell, 1.5 * R, th / 2)
    return tile


def field(tile, w, h):
    """Tile out to (w + tw, h + th) so a frame can be cropped at any offset."""
    tw, th = tile.size
    out = Image.new("RGBA", (w + tw, h + th), (0, 0, 0, 0))
    for y in range(0, out.height, th):
        for x in range(0, out.width, tw):
            out.alpha_composite(tile, (x, y))
    return out


# ----------------------------------------------------- calm ingredients ---
# Ashwagandha root, tea leaf (for L-theanine) and lemon balm. Same rules as
# the fruit above: drawn, so they take any size and any palette.
#
# These are built from an attachment point outward rather than by rotating
# leaf bitmaps into place. Rotating with expand=True loses track of where the
# leaf's base ended up, and every leaf floats a few pixels off its stem — the
# sprig reads as scattered foliage instead of a plant.

def _leaf_pts(bx, by, length, width, ang, teeth=0, n=120):
    """Outline of a leaf whose base sits at (bx, by), growing along `ang`.

    `ang` is radians clockwise from straight up, so 0 points at the top of
    the frame and positive leans right.
    """
    dx, dy = math.sin(ang), -math.cos(ang)      # along the midrib
    px, py = -dy, dx                            # across it
    right, left = [], []
    for i in range(n + 1):
        u = i / n                               # 0 at the base, 1 at the tip
        half = math.sin(math.pi * u) ** 0.62
        if teeth:
            half *= 1 + 0.085 * abs(math.sin(teeth * math.pi * u))
        a, s = u * length, half * width / 2
        right.append((bx + dx * a + px * s, by + dy * a + py * s))
        left.append((bx + dx * a - px * s, by + dy * a - py * s))
    return right + left[::-1]


def _leaf(d, bx, by, length, width, ang, fill, teeth=0, vein=None):
    d.polygon(_leaf_pts(bx, by, length, width, ang, teeth), fill=fill)
    if not vein:
        return
    dx, dy = math.sin(ang), -math.cos(ang)
    px, py = -dy, dx
    d.line([(bx + dx * length * 0.04, by + dy * length * 0.04),
            (bx + dx * length * 0.95, by + dy * length * 0.95)],
           fill=vein, width=max(1, int(width * 0.055)))
    for k in range(5):
        u = 0.20 + k * 0.145
        half = math.sin(math.pi * u) ** 0.62 * width * 0.38
        ax, ay = bx + dx * length * u, by + dy * length * u
        tx, ty = bx + dx * length * (u + 0.11), by + dy * length * (u + 0.11)
        for sgn in (-1, 1):
            d.line([(ax, ay), (tx + px * half * sgn, ty + py * half * sgn)],
                   fill=vein, width=max(1, int(width * 0.035)))


def tea_sprig(h, leaf_c, stem_c):
    """Two leaves and a terminal bud — L-theanine comes from the tea leaf."""
    W, H = int(h * 0.86 * SS), int(h * SS)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = W * 0.50
    d.line([(cx, H * 0.98), (cx, H * 0.20)], fill=stem_c,
           width=max(2, int(W * 0.030)))
    for u, side in ((0.68, 1), (0.52, -1), (0.36, 1)):
        _leaf(d, cx, H * u, H * 0.38, W * 0.155, side * 1.06, leaf_c,
              vein=stem_c)
    _leaf(d, cx, H * 0.24, H * 0.24, W * 0.085, 0.0, leaf_c)
    return _shrink(im)


def lemon_balm(h, leaf_c, vein_c):
    """Opposite pairs of serrated leaves, the way the plant actually grows."""
    W, H = int(h * 0.96 * SS), int(h * SS)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = W * 0.50
    d.line([(cx, H * 0.98), (cx, H * 0.22)], fill=vein_c,
           width=max(2, int(W * 0.028)))
    for u, ln, wd, ang in ((0.74, 0.38, 0.165, 1.12), (0.48, 0.30, 0.135, 0.98)):
        for side in (-1, 1):
            _leaf(d, cx, H * u, H * ln, W * wd, side * ang, leaf_c,
                  teeth=9, vein=vein_c)
    _leaf(d, cx, H * 0.28, H * 0.24, W * 0.105, 0.0, leaf_c, teeth=7,
          vein=vein_c)
    return _shrink(im)


def ashwagandha(h, root_c, leaf_c):
    """The taproot, which is the part that goes in the can."""
    W, H = int(h * 0.76 * SS), int(h * SS)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, crown, n = W * 0.50, H * 0.36, 80

    def spine(u):
        return cx + W * 0.075 * math.sin(u * 2.3), crown + (H - crown) * u

    right, left = [], []
    for i in range(n + 1):
        u = i / n
        x, y = spine(u)
        half = W * 0.095 * (1 - u) ** 0.65 + W * 0.006
        right.append((x + half, y))
        left.append((x - half, y))
    d.polygon(right + left[::-1], fill=root_c)

    for u, side, ln in ((0.26, -1, 0.24), (0.44, 1, 0.20),
                        (0.62, -1, 0.16), (0.78, 1, 0.12)):
        x, y = spine(u)
        d.line([(x, y), (x + side * W * ln, y + H * ln * 0.80)],
               fill=root_c, width=max(2, int(W * 0.050 * (1 - u))))

    for side in (-1, 1):
        _leaf(d, cx, crown + H * 0.01, H * 0.32, W * 0.135, side * 0.58,
              leaf_c)
    return _shrink(im)


def gradient_fill(size, c1, c2):
    """A diagonal two-stop ramp, built small and stretched."""
    n = 48
    g = Image.new("RGB", (n, n))
    p = g.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * (n - 1))
            p[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return g.resize(size, Image.BILINEAR).convert("RGBA")


def badge(mark, size, c1, c2, inset=0.62):
    """Set `mark` in white inside a gradient disc.

    The mark is knocked out by its alpha, not painted, so any gaps in it —
    the veins in a leaf, say — stay open and show the gradient through.
    That is how the supplied ashwagandha badge is built, and matching it is
    the whole point of this function.
    """
    up = size * 4                       # circle drawn large so the edge is clean
    mask = Image.new("L", (up, up), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, up - 1, up - 1], fill=255)
    disc = gradient_fill((size, size), c1, c2)
    disc.putalpha(mask.resize((size, size), Image.LANCZOS))

    box = size * inset
    k = min(box / mark.width, box / mark.height)
    m = mark.resize((max(1, round(mark.width * k)),
                     max(1, round(mark.height * k))), Image.LANCZOS)
    white = Image.new("RGBA", m.size, (255, 255, 255, 255))
    white.putalpha(m.getchannel("A"))
    blend(disc, white, (size - m.width) / 2, (size - m.height) / 2)
    return disc
