"""Generate the PWA icons (a gold diamond on dark) with pure stdlib PNG writing."""
import struct
import sys
import zlib
from pathlib import Path

BG = (13, 17, 23)
GOLD = (212, 160, 23)

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "frontend" / "icons"
EXT_ICON_DIR = ROOT / "extension" / "icons"


def write_png(path: Path, size: int) -> None:
    c = size / 2
    r = size * 0.34
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter byte
        for x in range(size):
            inside = abs(x - c) + abs(y - c) < r
            px = GOLD if inside else BG
            row.extend(px)
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
    EXT_ICON_DIR.mkdir(parents=True, exist_ok=True)
    for size in (16, 48, 128):
        write_png(EXT_ICON_DIR / f"icon-{size}.png", size)
    print(f"extension icons written to {EXT_ICON_DIR}")


if __name__ == "__main__":
    sys.exit(main())
