"""The voiced cut, edited to a supplied voice-over.

Three beats, one per line of the script:

    "4 flavors, 1 calm"          a hard cut to a new flavour on each syllable
    "Zen Joy is a delicious…"    the calm ingredients, rotating through
    "Find your zen with Zen Joy" the logo

The look is make_hero.py's, imported rather than restated, so a colour or
layout change lands in both films.

Nothing about the timing is typed in. syllables.py splits the recording into
its three lines and finds where each syllable of the first line actually
begins, so the edit follows the read. Re-record the voice-over — a different
artist, a different pace, a reordered script — drop it in as audio/vo.mp3,
update SCRIPT below, and the cuts move to match.

    python3 make_hero_vo.py [out.mov]
"""
import math
import pathlib
import subprocess
import sys

from PIL import Image

import icons
import make_hero as hero
import syllables

HERE = pathlib.Path(__file__).parent
AUDIO = HERE / "audio"
VO = AUDIO / "vo.mp3"
FFMPEG = "/usr/local/bin/ffmpeg"

# Syllable counts are how the recording gets divided; they are counted from
# the script by hand because that is the one thing the audio cannot tell us.
SCRIPT = [
    ("4 flavors, 1 calm", 5),
    ("Zen Joy is a delicious stress relief drink made with natural "
     "ingredients to help you relax.", 25),
    ("Find your zen with Zen Joy.", 6),
]

XF = 0.55                 # cross-fade into the logo card
TAIL = 1.60               # quiet on the logo after she finishes
SLIDE = 0.70              # how long one ingredient takes to rotate in

PAPER = (250, 249, 246)   # the calm middle, and a step toward the white card
LEAF = (104, 138, 98)     # the drawn plants, used only for the faint texture
VEIN = (58, 90, 60)
CLAY = (150, 112, 74)

# The gradient the supplied ashwagandha badge is built from, sampled off it
# so the two discs made here are indistinguishable from the one that shipped.
DISC = ((118, 49, 142), (170, 35, 107))

# Artwork is supplied, in ingredients/. `disc` says whether the file is a
# bare mark that still needs setting into a badge — the ashwagandha art
# already arrived as one.
INGREDIENTS = [
    ("ltheanine", "L-Theanine",
     "Extracted from green tea, this amino acid has been shown to help "
     "ease racing thoughts and keep you focused.", True),
    ("ashwagandha", "Ashwagandha (KSM-66)",
     "Clinically proven adaptogen that reduces stress and enhances mental "
     "clarity and resilience.", False),
    ("lemonbalm", "Lemon Balm",
     "An herbal remedy that calms, relaxes, and soothes the mind.", True),
]


def art(stem, size, disc):
    """Load a supplied icon, trim its margins, and return it at `size`.

    Everything ends up the same disc, so the three sit at identical weight
    on their slides no matter what aspect the source art was drawn at.
    """
    im = Image.open(HERE / "ingredients" / f"{stem}.png").convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    if bbox:
        im = im.crop(bbox)
    if disc:
        return icons.badge(im, size, *DISC)
    k = size / max(im.width, im.height)
    return im.resize((max(1, round(im.width * k)),
                      max(1, round(im.height * k))), Image.LANCZOS)


def duration(path):
    out = subprocess.run(["/usr/local/bin/ffprobe", "-v", "error",
                          "-show_entries", "format=duration", "-of",
                          "csv=p=0", str(path)], capture_output=True,
                         text=True, check=True)
    return float(out.stdout.strip())


# ----------------------------------------------------------------- frames ---

def frame_flavor(s, t):
    """A settled can on its flat field.

    Nothing eases in: each montage shot is a fraction of a second and an
    entrance animation would only ever be seen half-finished.
    """
    im = s["bg"].copy()
    drift = 4 * math.sin(2 * math.pi * (t + 1.2) / 7.0)
    hero.place(im, s["shadow"], hero.W / 2,
               hero.CAN_Y + s["can"].height / 2 + 6, "cm", alpha=0.9,
               dy=drift * 0.35)
    hero.place(im, s["can"], hero.W / 2, hero.CAN_Y, "cm", dy=drift)
    return im


def build_ingredients(span):
    """The calm middle: one field, its contents rotating through.

    The background is deliberately shared and still. Cutting between three
    backgrounds would read as three more places; holding one and moving only
    what is on it reads as a single view turning, which is the point.
    """
    bg = Image.new("RGBA", (hero.W, hero.H), PAPER + (255,))
    tile = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    motifs = [icons.ashwagandha(200, CLAY + (255,), LEAF + (255,)),
              icons.tea_sprig(210, LEAF + (255,), VEIN + (255,)),
              icons.lemon_balm(205, LEAF + (255,), VEIN + (255,)),
              icons.tea_sprig(150, LEAF + (255,), VEIN + (255,))]
    for m, (fx, fy, rot) in zip(motifs, [(0.24, 0.22, -11), (0.75, 0.29, 13),
                                         (0.27, 0.75, 8), (0.76, 0.79, -16)]):
        icons.stamp(tile, icons._alpha(icons._rot(m, rot), 0.055),
                    600 * fx, 600 * fy)
    bg.alpha_composite(icons.field(tile, hero.W, hero.H)
                       .crop((0, 0, hero.W, hero.H)))

    panels = []
    for stem, name, body, disc in INGREDIENTS:
        layer = Image.new("RGBA", (hero.W, hero.H), (0, 0, 0, 0))
        hero.place(layer, art(stem, 330, disc), hero.W / 2, 378, "cm")
        hero.place(layer, hero.fitted(name, 78, hero.MED, hero.INK + (255,),
                                      1300),
                   hero.W / 2, 646, "cm")
        hero.place(layer, hero.paragraph(body, hero.font(38, hero.LIGHT),
                                         hero.INK + (175,), 1180, 58),
                   hero.W / 2, 788, "ct")
        panels.append(layer)
    return dict(bg=bg, panels=panels, span=span / len(panels))


def frame_ingredients(s, t):
    im = s["bg"].copy()
    n = len(s["panels"])
    i = min(n - 1, int(t / s["span"]))
    local = t - i * s["span"]

    if i > 0 and local < SLIDE:
        p = hero.ease_out(local / SLIDE)
        hero.place(im, s["panels"][i - 1], -hero.W * 0.42 * p, 0, "lt",
                   alpha=1 - p)
        hero.place(im, s["panels"][i], hero.W * 0.42 * (1 - p), 0, "lt",
                   alpha=p)
    else:
        hero.place(im, s["panels"][i], 0, 0, "lt")
    return im


class Shot:
    """One cut. `xfade` of 0 is a hard cut, which is what a syllable gets."""

    def __init__(self, start, render, xfade=0.0):
        self.start, self.render, self.xfade = start, render, xfade


def render_at(shots, t):
    i = 0
    for k, sh in enumerate(shots):
        if t >= sh.start:
            i = k
    sh = shots[i]
    img = sh.render(t - sh.start)
    if sh.xfade > 0 and i > 0 and t - sh.start < sh.xfade:
        prev = shots[i - 1]
        img = Image.blend(prev.render(t - prev.start), img,
                          (t - sh.start) / sh.xfade)
    return img


# ------------------------------------------------------------------- main ---

def main(out):
    if not VO.exists():
        raise SystemExit(f"no voice-over at {VO}")
    wav = syllables.to_wav(VO, AUDIO / "vo.mono.wav")
    env, _, clip = syllables.envelope(wav)

    lines = syllables.split_lines(env, [n for _, n in SCRIPT])
    for (text, _), (a, b) in zip(SCRIPT, lines):
        print(f"  {a:5.2f}-{b:5.2f}s  {text[:52]}")

    # everything is measured from the first syllable, so the film starts on
    # the word rather than on the silence in front of it
    cuts = syllables.onsets(
        [v for i, v in enumerate(env)
         if lines[0][0] <= i * syllables.HOP <= lines[0][1]], SCRIPT[0][1])
    lead = lines[0][0] + cuts[0]
    cuts = [lines[0][0] + c - lead for c in cuts]
    ing_at = lines[1][0] - lead
    card_at = lines[2][0] - lead - XF
    total = lines[2][1] - lead + TAIL
    print("syllable cuts:", [round(c, 3) for c in cuts])

    flavors = [hero.build_flavor(fl) for fl in hero.FLAVORS]
    order = [0, 1, 2, 3, 0]              # "calm" lands back where it started
    shots = [Shot(t, lambda tl, s=flavors[i]: frame_flavor(s, tl))
             for t, i in zip(cuts, order)]
    ing = build_ingredients(card_at - ing_at)
    shots.append(Shot(ing_at, lambda tl: frame_ingredients(ing, tl), XF))
    card = hero.build_card(True, "find your zen")
    shots.append(Shot(card_at, lambda tl: hero.frame_card(card, tl), XF))

    frames = int(round(total * hero.FPS))
    print(f"{frames} frames ({total:.2f}s); ingredients {ing_at:.2f}s, "
          f"logo {card_at + XF:.2f}s")

    silent = out.with_suffix(".silent.mov")
    enc = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{hero.W}x{hero.H}", "-r",
         str(hero.FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset",
         "slow", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
         str(silent)], stdin=subprocess.PIPE)
    for f in range(frames):
        enc.stdin.write(render_at(shots, f / hero.FPS)
                        .convert("RGB").tobytes())
        if f % 120 == 0:
            print(f"  {f}/{frames}", flush=True)
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("video encode failed")

    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(silent), "-i", str(VO),
         "-filter_complex",
         f"[1:a]atrim=start={lead:.3f},asetpts=PTS-STARTPTS,"
         "aformat=channel_layouts=stereo,apad[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out)],
        check=True)
    silent.unlink()
    print("wrote", out, f"({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                      else HERE / "zenjoy-hero-vo.mov"))
