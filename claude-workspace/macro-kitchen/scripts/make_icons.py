"""Generate the PWA icons (a plate ring split into the three macros — protein,
carbs, fat — around a center dot) with stdlib PNG writing."""
import math
import struct
import sys
import zlib
from pathlib import Path

BG = (15, 26, 20)          # deep kitchen green
PROTEIN = (240, 113, 103)  # coral
CARBS = (245, 187, 73)     # amber
FAT = (96, 165, 250)       # sky
PLATE = (30, 48, 38)       # inner plate
CENTER = (74, 222, 128)    # fresh green pip

# macro split shown on the icon: 30% protein / 40% carbs / 30% fat
ARCS = [(0.00, 0.30, PROTEIN), (0.30, 0.70, CARBS), (0.70, 1.00, FAT)]

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "frontend" / "icons"


def write_png(path: Path, size: int) -> None:
    cx = cy = size / 2.0
    r_out = size * 0.40
    r_in = size * 0.28
    r_plate = size * 0.24
    r_pip = size * 0.09
    gap = 0.012            # small gap between arcs, as a fraction of the turn

    def px_color(x: float, y: float):
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy)
        if d <= r_pip:
            return CENTER
        if d <= r_plate:
            return PLATE
        if r_in <= d <= r_out:
            # angle as fraction of a turn, 12 o'clock = 0, clockwise
            frac = (math.atan2(dx, -dy) / (2 * math.pi)) % 1.0
            for a0, a1, color in ARCS:
                if a0 + gap <= frac < a1 - gap:
                    return color
        return BG

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
