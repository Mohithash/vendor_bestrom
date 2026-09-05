#!/usr/bin/env python3
"""BestROM ultraminimal bootanimation generator.

Design: pure black background, canonical BestROM mark only - the dotted
lowercase "b" (4-dot stem + 2x2 bowl = 8 grey circles), grey #8C919B, no
background text, no other glyphs. Geometry matches the mark already shipped
in packages/apps/SetupWizard/res/drawable/logo.xml and the
best-rom-branding-mark branch of bestrom-peridot-source: r=24 on a 62 pitch,
centred in a 400x400 viewport (bbox x114..286 y83..317).

No Pillow required - pure Python PNG.

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
GREY = (140, 145, 155)      # #8C919B - canonical mark colour
GREY_BRIGHT = (200, 205, 210)  # #C8CDD2 - breathing highlight only
BLACK = (0, 0, 0)

# --- canonical mark geometry (viewport units, matches logo.xml) ---
VP = 400.0
MARK_R = 24.0
# centres: (x, y) in the 400x400 viewport, taken directly from logo.xml /
# best_rom_mark_spacious.xml (M x,(y-r) a r,r ... -> centre (x,y))
MARK_DOTS = [
    (138, 107), (138, 169), (138, 231), (138, 293),  # stem, 4 dots
    (200, 169), (262, 169),                          # bowl top row
    (200, 293), (262, 293),                          # bowl bottom row
]
MARK_BBOX = (114, 83, 286, 317)  # x0, y0, x1, y1

# scale so the mark's height is ~30% of the frame height, centred in frame
_bbox_h = MARK_BBOX[3] - MARK_BBOX[1]
_bbox_cx = (MARK_BBOX[0] + MARK_BBOX[2]) / 2.0
_bbox_cy = (MARK_BBOX[1] + MARK_BBOX[3]) / 2.0
SCALE = (H * 0.30) / _bbox_h
DOT_R = MARK_R * SCALE

CENTERS_PX = [
    (
        W / 2.0 + (x - _bbox_cx) * SCALE,
        H / 2.0 + (y - _bbox_cy) * SCALE,
    )
    for (x, y) in MARK_DOTS
]


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
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))


def draw_dot(buf, w, h, cx: float, cy: float, r: float, rgb, phase: float = 1.0) -> None:
    """Draw one filled circular dot. phase<1 reveals it via a stable
    per-pixel threshold (dissolve-in), phase>=1 draws it solid."""
    icx, icy = round(cx), round(cy)
    ir = int(r) + 1
    r2 = r * r
    for dy in range(-ir, ir + 1):
        for dx in range(-ir, ir + 1):
            if dx * dx + dy * dy > r2:
                continue
            if phase < 1.0:
                v = ((icx * 17 + icy * 31 + dx * 7 + dy * 13) % 100) / 100.0
                if v > phase:
                    continue
            set_px(buf, w, h, icx + dx, icy + dy, rgb)


def draw_mark(buf, w, h, rgb, phase: float = 1.0) -> None:
    for cx, cy in CENTERS_PX:
        draw_dot(buf, w, h, cx, cy, DOT_R, rgb, phase)


def frame_png(kind: str, t: float) -> bytes:
    buf = bytearray(blank(W, H, BLACK))
    if kind == "fade_in":
        # dots dissolve in and brighten from grey towards grey-bright
        col = blend(GREY, GREY_BRIGHT, min(1.0, t * 0.6))
        draw_mark(buf, W, H, col, phase=min(1.0, t * 1.1))
    elif kind == "pulse":
        # slow gentle breathing between grey and grey-bright, mark fully drawn
        col = blend(GREY, GREY_BRIGHT, t)
        draw_mark(buf, W, H, col, phase=1.0)
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

    # part0: fade-in of the dots, plays once
    n0 = 24
    for i in range(n0):
        t = i / max(1, n0 - 1)
        (part0 / f"{i:05d}.png").write_bytes(frame_png("fade_in", t))

    # part1: slow gentle pulse, loops until boot completes
    n1 = 36
    for i in range(n1):
        t = i / n1  # full period over n1 frames, wraps cleanly for looping
        import math

        pulse = (1 - math.cos(2 * math.pi * t)) / 2.0  # 0..1..0 smooth
        (part1 / f"{i:05d}.png").write_bytes(frame_png("pulse", pulse))

    # c = complete part even if boot finishes; p 0 = loop until boot done
    desc = f"""{W} {H} 30
c 1 0 part0
p 0 0 part1
"""
    (gen / "desc.txt").write_text(desc)

    media = vendor / "prebuilt" / "common" / "media"
    media.mkdir(parents=True, exist_ok=True)

    # remove stray unused wallpaper PNGs if present
    for stray in ("bestrom-wallpaper.png", "bestrom-wallpaper-dots.png"):
        p = media / stray
        if p.exists():
            p.unlink()

    zip_path = media / "bootanimation.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("desc.txt", desc)
        for part in ("part0", "part1"):
            for f in sorted((gen / part).glob("*.png")):
                z.write(f, f"{part}/{f.name}")

    total_frames = n0 + n1
    print(f"OK {zip_path} ({zip_path.stat().st_size} bytes) {W}x{H} fps30 frames={total_frames}")


if __name__ == "__main__":
    main()
