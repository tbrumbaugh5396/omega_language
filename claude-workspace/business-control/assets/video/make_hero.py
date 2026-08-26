"""Builds the homepage hook video: "4 flavors, 1 calm".

Six segments — a title card, one per flavour, and a logo card — cross-faded
into a single 1920x1080 clip. Each flavour is a centred can on a flat field
of its own colour, over a still tessellation of its ingredient (icons.py),
with the label set underneath.

Type is Quicksand, the same face the site declares as `--wordmark`, so the
headlines and the logo speak with one voice rather than two. It ships as a
variable font and the weight axis is set per call — one file covers Light
through Bold.

Everything that can be flat is flat: no gradients, no vignette, no drifting
background. That is a design decision, but it is also why a segment's whole
background can be composed once and copied per frame — the only things that
move are the can and the words.

Frames are piped straight into ffmpeg as raw RGB rather than written out as
PNGs. Seven hundred stills of a 1080p frame is about a gigabyte of disk and a
lot of encode/decode for no gain.

The cans are the real product renders in assets/cans/<key>.png. draw_can
falls back to drawing one if a file is missing, so a new flavour can be
roughed in before its photography exists.

    python3 make_hero.py [out.mov]
"""
import math
import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import icons

HERE = pathlib.Path(__file__).parent
CANS = HERE.parent / "cans"
QUICKSAND = HERE / "fonts" / "Quicksand.ttf"

W, H = 1920, 1080
FPS = 30
XF = 0.55                     # cross-fade between segments, seconds

LIGHT, REG, MED, SEMI, BOLD = 300, 400, 500, 600, 700

WHITE = (255, 255, 255)
INK = (58, 50, 44)            # warm near-black, softer than pure black


def font(size, weight=REG):
    f = ImageFont.truetype(str(QUICKSAND), size)
    f.set_variation_by_axes([weight])
    return f


# Flat brand colours — one tone each, no ramp.
FLAVORS = [
    dict(key="mango", name="Mango", tea="black tea",
         bg=(226, 126, 52), ink=(255, 250, 244)),
    dict(key="passionfruit", name="Passion Fruit", tea="green tea",
         bg=(176, 48, 100), ink=(255, 244, 249)),
    dict(key="lavender", name="Lavender", tea="black tea",
         bg=(116, 102, 176), ink=(247, 245, 255)),
    dict(key="honey", name="Honey Green Tea", tea="with real honey",
         bg=(122, 158, 76), ink=(249, 253, 242)),
]


# ------------------------------------------------------------- utilities ---

def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def text_image(text, f, fill, track=0):
    """Render a line to its own layer so it can be faded and moved freely."""
    pad = 40
    if track:
        width = sum(f.getlength(c) for c in text) + track * (len(text) - 1)
    else:
        width = f.getlength(text)
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (int(width) + pad * 2, asc + desc + pad * 2),
                   (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if track:
        x = pad
        for c in text:
            d.text((x, pad), c, font=f, fill=fill)
            x += f.getlength(c) + track
    else:
        d.text((pad, pad), text, font=f, fill=fill)     # keeps real kerning
    return im.crop(im.getbbox() or (0, 0, 1, 1))


def paragraph(text, f, fill, max_w, leading):
    """Wrap `text` to `max_w` and centre the lines on a shared baseline grid.

    Drawn line by line at a fixed leading rather than stacking cropped
    single-line images: cropping to ink means a line without descenders comes
    out shorter, and stacking those makes the baselines wander.
    """
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)

    asc, desc = f.getmetrics()
    w = int(max(f.getlength(ln) for ln in lines)) + 8
    im = Image.new("RGBA", (w, int(leading * (len(lines) - 1) + asc + desc)),
                   (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k, ln in enumerate(lines):
        d.text(((w - f.getlength(ln)) / 2, k * leading), ln, font=f, fill=fill)
    return im


def fitted(text, size, weight, fill, max_w, track=0):
    """Set a line at `size`, stepping down until it fits the width given."""
    while True:
        im = text_image(text, font(size, weight), fill, track)
        if im.width <= max_w or size <= 40:
            return im
        size -= 4


def place(canvas, im, x, y, anchor="lt", alpha=1.0, dy=0.0):
    if im is None or alpha <= 0.003:
        return
    ax = {"l": 0, "c": im.width / 2, "r": im.width}[anchor[0]]
    ay = {"t": 0, "m": im.height / 2, "b": im.height}[anchor[1]]
    icons.blend(canvas, icons._alpha(im, alpha), x - ax, y - ay + dy)


LOGO = Image.open(HERE / "logo.png").convert("RGBA")


def logo(width, color=None):
    """The wordmark at any width; `color` flattens it to one solid tone."""
    im = LOGO.resize((width, max(1, round(LOGO.height * width / LOGO.width))),
                     Image.LANCZOS)
    if color is None:
        return im
    solid = Image.new("RGBA", im.size, tuple(color) + (255,))
    solid.putalpha(im.getchannel("A"))
    return solid


# ------------------------------------------------------------------ cans ---

def draw_can(height, fl):
    """The product render, or a drawn stand-in if that file is missing.

    The stand-in sells the cylinder entirely with shading: a dark edge on each
    side and one bright vertical highlight. Without those it reads as a flat
    rectangle no matter how good the label is.
    """
    real = CANS / f"{fl['key']}.png"
    if real.exists():
        im = Image.open(real).convert("RGBA")
        return im.resize((round(im.width * height / im.height), height),
                         Image.LANCZOS)

    S = 2                                   # draw double-size, shrink at the end
    h = height * S
    w = int(h * 0.361)
    body_top, body_bot = h * 0.075, h * 0.985
    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bd.rounded_rectangle([0, body_top, w - 1, body_bot],
                         radius=w * 0.17, fill=tuple(fl["bg"]) + (255,))
    silhouette = body.getchannel("A")

    shade = Image.new("RGBA", (w, 1), (0, 0, 0, 0))
    glare = Image.new("RGBA", (w, 1), (0, 0, 0, 0))
    sp, gp = shade.load(), glare.load()
    for x in range(w):
        u = x / (w - 1)
        edge = min(1.0, ((2 * u - 1) ** 2) * (1.0 if u < 0.5 else 1.25))
        sp[x, 0] = (0, 0, 0, int(150 * edge ** 1.3))
        gp[x, 0] = (255, 255, 255,
                    int(120 * math.exp(-((u - 0.31) / 0.115) ** 2)))
    for layer in (shade, glare):
        big = layer.resize((w, h), Image.NEAREST)
        big.putalpha(Image.composite(big.getchannel("A"),
                                     Image.new("L", (w, h), 0), silhouette))
        body.alpha_composite(big)

    d = ImageDraw.Draw(body)
    nw = w * 0.80
    d.rounded_rectangle([(w - nw) / 2, h * 0.012, (w + nw) / 2, h * 0.105],
                        radius=nw * 0.22, fill=(191, 195, 200, 255))
    d.ellipse([(w - nw) / 2, h * 0.004, (w + nw) / 2, h * 0.052],
              fill=(214, 217, 221, 255))
    d.ellipse([w * .06, body_bot - h * .022, w - w * .06, body_bot + h * .004],
              fill=(0, 0, 0, 70))
    place(body, logo(int(w * 0.66), WHITE), w / 2, h * 0.32, "cm")
    place(body, text_image(fl["name"].upper(), font(int(h * 0.032), SEMI),
                           WHITE + (240,), track=h * 0.006),
          w / 2, h * 0.45, "cm")
    return body.resize((w // S, h // S), Image.LANCZOS)


def can_shadow(can):
    """Contact shadow — a blurred ellipse, so the can sits on something."""
    pad = int(can.width * 0.9)
    im = Image.new("RGBA", (can.width + pad * 2, int(can.width * 0.8)),
                   (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse(
        [pad * 0.85, im.height * 0.34,
         im.width - pad * 0.85, im.height * 0.72], fill=(0, 0, 0, 44))
    return im.filter(ImageFilter.GaussianBlur(im.width * 0.075))


# -------------------------------------------------------------- segments ---

def flavor_tile(fl):
    """The ingredient tessellation, tone on tone.

    Every motif is white at a different opacity rather than a second hue: on a
    flat field, one colour plus transparency stays quiet, and two colours
    start competing with the can.
    """
    k = fl["key"]
    if k == "mango":
        return icons.tile_scatter(
            lambda s: icons.mango(s, WHITE + (160,), WHITE + (255,)),
            340, dim=0.21)
    if k == "passionfruit":
        return icons.tile_scatter(
            lambda s: icons.passionfruit(s, WHITE + (95,), WHITE + (135,),
                                         WHITE + (255,)),
            340, dim=0.23)
    if k == "lavender":
        return icons.tile_scatter(
            lambda s: icons.lavender(s, WHITE + (130,), WHITE + (245,)),
            340, dim=0.21)
    return icons.tile_honeycomb(82, WHITE + (255,), WHITE + (55,), 4.0,
                                dim=0.17)


CAN_H, CAN_Y = 636, 424               # centred group: can, then label beneath


def build_flavor(fl):
    """Everything about one flavour segment that does not change per frame."""
    bg = Image.new("RGBA", (W, H), tuple(fl["bg"]) + (255,))
    bg.alpha_composite(icons.field(flavor_tile(fl), W, H).crop((0, 0, W, H)))
    can = draw_can(CAN_H, fl)
    ink = tuple(fl["ink"])
    return dict(
        bg=bg, can=can, shadow=can_shadow(can),
        name=fitted(fl["name"], 78, MED, ink + (255,), 1180),
        tea=text_image(fl["tea"], font(31, LIGHT), ink + (185,), track=4.5),
    )


def frame_flavor(s, t):
    im = s["bg"].copy()

    a = ease_out(t / 0.9)
    drift = (1 - a) * 64 + 4 * math.sin(2 * math.pi * (t + 1.2) / 7.0)
    place(im, s["shadow"], W / 2, CAN_Y + s["can"].height / 2 + 6, "cm",
          alpha=a * 0.9, dy=drift * 0.35)
    place(im, s["can"], W / 2, CAN_Y, "cm", alpha=a, dy=drift)

    p = ease_out((t - 0.42) / 0.7)
    place(im, s["name"], W / 2, 846, "cm", alpha=p, dy=(1 - p) * 24)
    p = ease_out((t - 0.60) / 0.7)
    place(im, s["tea"], W / 2, 928, "cm", alpha=p, dy=(1 - p) * 20)
    return im


def build_card(closing, line="4 flavors, 1 calm"):
    """Title and logo cards: plain white, nothing behind the words.

    `line` is a parameter because the closing card should echo whatever
    tagline was just spoken over it, which is not always the opening one.
    """
    return dict(
        bg=Image.new("RGBA", (W, H), WHITE + (255,)),
        line=text_image(line, font(150, LIGHT), INK + (255,)),
        mark=logo(660),
        closing=closing,
    )


def frame_card(s, t):
    im = s["bg"].copy()
    if s["closing"]:
        p = ease_out(t / 1.0)
        m = s["mark"]
        k = 0.95 + 0.05 * p
        m = m.resize((int(m.width * k), int(m.height * k)), Image.LANCZOS)
        place(im, m, W / 2, 470, "cm", alpha=p, dy=(1 - p) * 14)
        p2 = ease_out((t - 0.55) / 0.9)
        small = s["line"].resize((int(s["line"].width * 0.40),
                                  int(s["line"].height * 0.40)), Image.LANCZOS)
        place(im, small, W / 2, 672, "cm", alpha=p2 * 0.85, dy=(1 - p2) * 18)
    else:
        p = ease_out((t - 0.25) / 1.1)
        place(im, s["line"], W / 2, H / 2, "cm", alpha=p, dy=(1 - p) * 30)
    return im


# -------------------------------------------------------------- timeline ---

def main(out):
    print("building layers…", flush=True)
    segments = [(4.0, frame_card, build_card(False))]
    for fl in FLAVORS:
        segments.append((4.3, frame_flavor, build_flavor(fl)))
        print(f"  {fl['key']}", flush=True)
    segments.append((4.0, frame_card, build_card(True)))

    starts, at = [], 0.0
    for dur, _, _ in segments:
        starts.append(at)
        at += dur - XF
    total = starts[-1] + segments[-1][0]
    frames = int(round(total * FPS))

    cmd = ["/usr/local/bin/ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-an",
           "-c:v", "libx264", "-preset", "slow", "-crf", "17",
           "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    print(f"rendering {frames} frames ({total:.1f}s)…", flush=True)
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for f in range(frames):
        t = f / FPS
        live = [(i, t - starts[i]) for i in range(len(segments))
                if 0 <= t - starts[i] < segments[i][0]]
        if not live:
            live = [(len(segments) - 1, segments[-1][0] - 1e-3)]
        i, tl = live[0]
        img = segments[i][1](segments[i][2], tl)
        if len(live) > 1:                       # cross-fade into the next one
            j, tj = live[1]
            nxt = segments[j][1](segments[j][2], tj)
            img = Image.blend(img, nxt, min(1.0, max(0.0, tj / XF)))
        enc.stdin.write(img.convert("RGB").tobytes())
        if f % 120 == 0:
            print(f"  {f}/{frames}", flush=True)

    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    print("wrote", out, f"({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                      else HERE / "zenjoy-hero.mov"))
