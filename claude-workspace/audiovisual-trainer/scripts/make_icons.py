"""Generate the PWA icons — an aperture ring with a spectrum inside it, the
two crafts in one mark — with stdlib PNG writing."""
import math
import struct
import sys
import zlib
from pathlib import Path

BG = (13, 15, 24)        # near-black indigo
RING = (124, 156, 255)   # periwinkle — the lens
FIELD = (20, 24, 38)     # inside the aperture
WARM = (240, 163, 94)    # amber bars
COOL = (110, 231, 200)   # mint bars

# Bar heights as a fraction of the field radius, left to right. Fixed rather
# than random so the icon is stable across regenerations.
BARS = [0.34, 0.62, 0.88, 0.52, 0.74, 0.41, 0.66, 0.29]

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "frontend" / "icons"


def write_png(path: Path, size: int) -> None:
    cx = cy = size / 2.0
    r_out = size * 0.44
    r_in = size * 0.355
    n = len(BARS)
    span = r_in * 1.5            # total width the bars occupy
    bar_w = span / n
    gap = bar_w * 0.28

    def px_color(x: float, y: float):
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy)
        if d > r_out:
            return BG
        if d > r_in:
            return RING
        # inside the aperture: draw the spectrum
        i = int((dx + span / 2) // bar_w)
        if 0 <= i < n:
            off = (dx + span / 2) - i * bar_w
            if off > gap / 2 and off < bar_w - gap / 2:
                h = BARS[i] * r_in
                if abs(dy) <= h:
                    return WARM if i % 2 == 0 else COOL
        return FIELD

    rows = []
    for y in range(size):
        row = bytearray([0])  # filter byte
        for x in range(size):
            row.extend(px_color(x + 0.5, y + 0.5))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data)))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        write_png(ICON_DIR / f"icon-{size}.png", size)
    print(f"icons written to {ICON_DIR}")


if __name__ == "__main__":
    sys.exit(main())
