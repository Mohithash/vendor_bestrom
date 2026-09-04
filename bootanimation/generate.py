#!/usr/bin/env python3
"""BestROM ultraminimal bootanimation generator.

Design: pure black + grey dotted B / BESTROM (Monochrome Night).
No Pillow required — pure Python PNG.

Usage (from Android tree root or this directory):
  python3 vendor/bestrom/bootanimation/generate.py
  # writes vendor/bestrom/prebuilt/common/media/bootanimation.zip
"""
from __future__ import annotations

import struct
import zlib
import zipfile
from pathlib import Path

W, H = 1080, 2400
DOT_R = 3
GREY_DIM = (60, 60, 64)
GREY = (140, 145, 155)
GREY_BRIGHT = (200, 205, 210)
BLACK = (0, 0, 0)

B_GLYPH = [
    "#####",
    "#   #",
    "#   #",
    "#####",
    "#   #",
    "#   #",
    "#####",
]

GLYPHS = {
    "B": ["#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"],
    "S": [" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    "R": ["#### ", "#   #", "#   #", "#### ", "#  # ", "#   #", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "M": ["#   #", "## ##", "# # #", "#   #", "#   #", "#   #", "#   #"],
    " ": ["     ", "     ", "     ", "     ", "     ", "     ", "     "],
}


def png_rgb(w: int, h: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b""
    stride = w * 3
    for y in range(h):
        raw += b"\x00" + pixels[y * stride : (y + 1) * stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def blank(w: int, h: int, rgb=BLACK) -> bytes:
    r, g, b = rgb
    return bytes([r, g, b]) * (w * h)


def set_px(buf: bytearray, w: int, h: int, x: int, y: int, rgb) -> None:
    if 0 <= x < w and 0 <= y < h:
        i = (y * w + x) * 3
        buf[i], buf[i + 1], buf[i + 2] = rgb


def blend(c0, c1, t: float):
    return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))


def draw_glyph(buf, w, h, glyph, ox, oy, step, rgb, phase=1.0) -> None:
    for gy, row in enumerate(glyph):
        for gx, ch in enumerate(row):
            if ch != "#":
                continue
            cx = ox + gx * step
            cy = oy + gy * step
            for dy in range(-DOT_R, DOT_R + 1):
                for dx in range(-DOT_R, DOT_R + 1):
                    if dx * dx + dy * dy > DOT_R * DOT_R:
                        continue
                    if phase < 1.0:
                        v = ((cx * 17 + cy * 31 + dx * 3) % 100) / 100.0
                        if v > phase:
                            continue
                    set_px(buf, w, h, cx + dx, cy + dy, rgb)


def draw_bestrom_word(buf, w, h, cx, cy, step, rgb, phase=1.0) -> None:
    word = "BESTROM"
    gw, gap = 5, 1
    total_cells = len(word) * (gw + gap) - gap
    total_px = total_cells * step
    x0 = cx - total_px // 2
    y0 = cy - (7 * step) // 2
    for i, ch in enumerate(word):
        g = GLYPHS.get(ch, GLYPHS[" "])
        draw_glyph(buf, w, h, g, x0 + i * (gw + gap) * step, y0, step, rgb, phase)


def frame_png(kind: str, t: float) -> bytes:
    buf = bytearray(blank(W, H, BLACK))
    step = 18
    b_w, b_h = 5 * step, 7 * step
    ox = (W - b_w) // 2
    oy = (H - b_h) // 2 - 40

    if kind == "fade_b":
        col = blend(GREY_DIM, GREY_BRIGHT, min(1.0, t * 1.2))
        draw_glyph(buf, W, H, B_GLYPH, ox, oy, step, col, phase=min(1.0, t * 1.15))
    elif kind == "hold_b":
        draw_glyph(buf, W, H, B_GLYPH, ox, oy, step, GREY_BRIGHT, phase=1.0)
        alpha = min(1.0, max(0.0, (t - 0.15) / 0.5))
        if alpha > 0:
            col = blend(BLACK, GREY, alpha * 0.85)
            draw_bestrom_word(buf, W, H, W // 2, oy + b_h + 80, 8, col, phase=alpha)
    elif kind == "hold_full":
        draw_glyph(buf, W, H, B_GLYPH, ox, oy, step, GREY_BRIGHT, phase=1.0)
        draw_bestrom_word(buf, W, H, W // 2, oy + b_h + 80, 8, GREY, phase=1.0)
    elif kind == "fade_out":
        col = blend(GREY_BRIGHT, BLACK, t)
        col2 = blend(GREY, BLACK, t)
        draw_glyph(buf, W, H, B_GLYPH, ox, oy, step, col, phase=1.0)
        draw_bestrom_word(buf, W, H, W // 2, oy + b_h + 80, 8, col2, phase=1.0)
    return png_rgb(W, H, bytes(buf))


def main() -> None:
    # Resolve tree root: .../vendor/bestrom/bootanimation -> tree is parents[2]
    here = Path(__file__).resolve().parent
    if (here.parent / "prebuilt").is_dir():
        vendor = here.parent  # vendor/bestrom
    else:
        vendor = Path("vendor/bestrom")

    gen = here / "gen"
    if gen.exists():
        import shutil

        shutil.rmtree(gen)
    part0, part1 = gen / "part0", gen / "part1"
    part0.mkdir(parents=True)
    part1.mkdir(parents=True)

    n0 = 36
    for i in range(n0):
        t = i / max(1, n0 - 1)
        if t < 0.55:
            data = frame_png("fade_b", t / 0.55)
        else:
            data = frame_png("hold_b", (t - 0.55) / 0.45)
        (part0 / f"{i:05d}.png").write_bytes(data)

    n1 = 12
    for i in range(n1):
        (part1 / f"{i:05d}.png").write_bytes(frame_png("hold_full", 1.0))

    # c = complete part even if boot finishes; p 0 = loop until boot done
    desc = f"""{W} {H} 30
c 1 0 part0
p 0 0 part1
"""
    (gen / "desc.txt").write_text(desc)

    media = vendor / "prebuilt" / "common" / "media"
    media.mkdir(parents=True, exist_ok=True)
    zip_path = media / "bootanimation.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("desc.txt", desc)
        for part in ("part0", "part1"):
            for f in sorted((gen / part).glob("*.png")):
                z.write(f, f"{part}/{f.name}")

    # default wallpapers
    (media / "bestrom-wallpaper.png").write_bytes(png_rgb(W, H, blank(W, H, BLACK)))
    wb = bytearray(blank(W, H, BLACK))
    for y in range(40, H, 48):
        for x in range(40, W, 48):
            if (x + y) % 96 == 0:
                set_px(wb, W, H, x, y, GREY_DIM)
    (media / "bestrom-wallpaper-dots.png").write_bytes(png_rgb(W, H, bytes(wb)))

    print(f"OK {zip_path} ({zip_path.stat().st_size} bytes) {W}x{H} fps30")


if __name__ == "__main__":
    main()
