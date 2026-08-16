import os, math, cairosvg

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
os.makedirs(OUT, exist_ok=True)
FONT = "DejaVu Sans, Helvetica Neue, Helvetica, Arial, sans-serif"

THEMES = {
    "light": dict(bg="#FFFFFF", fg="#2C2C2A", mut="#5F5E5A", axis="#8B8A83",
                  blue="#2E7BC4", green="#5A8C1E", coral="#C8502A", neutral="#8B8A83"),
    "dark":  dict(bg="#16161A", fg="#EDEBE4", mut="#B4B2A9", axis="#9C9A92",
                  blue="#6FB0EC", green="#9FCB60", coral="#EE8A62", neutral="#9C9A92"),
}

def arrow(x1, y1, x2, y2, col, w=1.6, head=7.0):
    """Line with an explicit chevron head -- no marker, no context-stroke."""
    ang = math.atan2(y2 - y1, x2 - x1)
    pts = []
    for d in (ang + math.radians(148), ang - math.radians(148)):
        pts.append((x2 + head * math.cos(d), y2 + head * math.sin(d)))
    (ax1, ay1), (ax2, ay2) = pts
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" '
            f'stroke-width="{w}" stroke-linecap="round"/>\n'
            f'<path d="M{ax1:.1f},{ay1:.1f} L{x2},{y2} L{ax2:.1f},{ay2:.1f}" fill="none" '
            f'stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>\n')

def head_svg(w, h, t, title, desc):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img">\n<title>{title}</title>\n<desc>{desc}</desc>\n'
            f'<style>\ntext {{ font-family: {FONT}; }}\n'
            f'.h {{ font-size: 16px; font-weight: 500; fill: {t["fg"]}; }}\n'
            f'.t {{ font-size: 14px; font-weight: 500; fill: {t["fg"]}; }}\n'
            f'.s {{ font-size: 12px; font-weight: 400; fill: {t["mut"]}; }}\n</style>\n'
            f'<rect width="{w}" height="{h}" fill="{t["bg"]}"/>\n')

def fig_wave(t):
    c, ax, bl = t["coral"], t["axis"], t["blue"]
    s = head_svg(680, 450, t,
        "Electromagnetic plane wave: graph versus field in space",
        "Top panel shows the familiar sine curve as a graph of electric field strength "
        "against position. Bottom panel shows the same wave as parallel sheets in space, "
        "each sheet carrying one uniform field vector that flips direction every half wavelength.")
    s += '<text class="h" x="340" y="32" text-anchor="middle">Plane wave: the graph vs. the field in space</text>\n'

    s += arrow(60, 160, 638, 160, ax, 0.9, 6)
    s += (f'<path d="M80,160 Q135,70 190,160 Q245,250 300,160 Q355,70 410,160 '
          f'Q465,250 520,160 Q575,70 630,160" fill="none" stroke="{c}" stroke-width="1.8"/>\n')
    for x, y in [(135,118),(245,202),(355,118),(465,202),(575,118)]:
        s += arrow(x, 160, x, y, c)
    s += ('<text class="s" x="340" y="242" text-anchor="middle">A graph \u2014 arrow length is '
          'field strength, not sideways motion</text>\n')

    s += arrow(60, 340, 638, 340, ax, 0.9, 6)
    for x, amp in [(110,1),(220,0),(330,-1),(440,0),(550,1)]:
        col = c if amp > 0 else (bl if amp < 0 else None)
        dash = ' stroke-dasharray="3 3"' if amp == 0 else ""
        s += (f'<polygon points="{x},300 {x+40},278 {x+40},368 {x},390" '
              f'fill="{col or "none"}" fill-opacity="{0.10 if col else 0}" '
              f'stroke="{ax}" stroke-width="0.9"{dash}/>\n')
        for dx, by in [(8,341),(20,334),(32,327)]:
            if amp == 0:
                s += f'<circle cx="{x+dx}" cy="{by}" r="2.2" fill="{ax}"/>\n'
            else:
                s += arrow(x+dx, by, x+dx, by - 26 if amp > 0 else by + 26, col)
    s += ('<text class="s" x="340" y="422" text-anchor="middle">In space \u2014 each sheet carries '
          'one uniform field value, flipping every half wavelength</text>\n')
    return s + "</svg>\n"

def fig_cones(t):
    b, g, r, ax, nu = t["blue"], t["green"], t["coral"], t["axis"], t["neutral"]
    s = head_svg(680, 495, t,
        "Cone sensitivity curves and metamerism",
        "Top panel shows the three human cone sensitivity curves, S, M and L, broad and "
        "heavily overlapping across roughly 400 to 700 nanometres. Bottom panel shows two "
        "completely different spectra, one broad hump and one pair of narrow green and red "
        "spikes, each producing an identical triple of S, M and L cone responses.")
    s += ('<text class="h" x="340" y="32" text-anchor="middle">Cone response: three numbers '
          'from a whole spectrum</text>\n')

    s += f'<line x1="60" y1="210" x2="638" y2="210" stroke="{ax}" stroke-width="0.9"/>\n'
    for d, col in [("M70,210 Q79,126 200,210", b), ("M180,210 Q282,94 520,210", g),
                   ("M210,210 Q342,86 590,210", r)]:
        s += f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.8"/>\n'
    for x, y, lab, col in [(107,158,"S",b),(300,140,"M",g),(390,136,"L",r)]:
        s += f'<text class="t" x="{x}" y="{y}" text-anchor="middle" fill="{col}">{lab}</text>\n'
    s += '<text class="s" x="70" y="228" text-anchor="middle">400 nm</text>\n'
    s += '<text class="s" x="620" y="228" text-anchor="middle">700 nm</text>\n'

    for base, ay in [(330,305),(430,405)]:
        s += f'<line x1="65" y1="{base}" x2="255" y2="{base}" stroke="{ax}" stroke-width="0.9"/>\n'
        s += arrow(270, ay, 395, ay, ax, 1.3)
        for bx, col, h in [(420,b,18),(470,g,52),(520,r,62)]:
            s += (f'<rect x="{bx}" y="{base-h}" width="30" height="{h}" rx="2" '
                  f'fill="{col}" fill-opacity="0.55"/>\n')
        for bx, lab in [(435,"S"),(485,"M"),(535,"L")]:
            s += f'<text class="s" x="{bx}" y="{base+15}" text-anchor="middle">{lab}</text>\n'

    s += (f'<path d="M90,330 Q170,230 250,330 Z" fill="{nu}" fill-opacity="0.20" '
          f'stroke="{nu}" stroke-width="1.4"/>\n')
    s += f'<rect x="149" y="385" width="10" height="45" fill="{g}" fill-opacity="0.75"/>\n'
    s += f'<rect x="197" y="375" width="10" height="55" fill="{r}" fill-opacity="0.75"/>\n'
    s += ('<text class="s" x="340" y="472" text-anchor="middle">Different spectra, identical '
          'response \u2014 a metamer</text>\n')
    return s + "</svg>\n"

for name, fn in {"em-plane-wave": fig_wave, "cone-metamerism": fig_cones}.items():
    for theme, t in THEMES.items():
        svg = fn(t)
        open(f"{OUT}/{name}-{theme}.svg", "w").write(svg)
        cairosvg.svg2png(bytestring=svg.encode(), write_to=f"{OUT}/{name}-{theme}.png",
                         scale=3, background_color=t["bg"])
print("\n".join(sorted(os.listdir(OUT))))
