#!/usr/bin/env python3
"""Appstore banners for Portal Turret, from the screenshots that
tools/capture_store.py takes.

Outputs (720x320, the appstore banner size):
  store/banner-dark.png    a dark test chamber, the turret scanning and the eye
  store/banner-light.png   white chamber panels, the eye and the checkered room

Usage: python3 tools/make_store_assets.py   (needs Pillow and numpy)
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "store"
SHOTS = STORE / "screenshots"
BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
W, H = 720, 320
RED = (230, 30, 30)


def shot(name):
    return Image.open(SHOTS / name).convert("RGB")


def framed_emery(img):
    """A Pebble Time 2-ish frame: dark body, screen inset."""
    bw, bh = img.width + 36, img.height + 64
    out = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], 30, fill=(28, 28, 32))
    d.rounded_rectangle([3, 3, bw - 4, bh - 4], 28, outline=(70, 70, 78), width=2)
    out.paste(img, (18, 32))
    return out


def framed_gabbro(img):
    """A Pebble Round 2-ish frame: round bezel."""
    r, b = img.width // 2, 18
    size = img.width + 2 * b
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    d.ellipse([0, 0, size - 1, size - 1], fill=(28, 28, 32))
    d.ellipse([3, 3, size - 4, size - 4], outline=(70, 70, 78), width=2)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    out.paste(img, (b, b), mask)
    return out


def paste_with_shadow(canvas, img, x, y, color=(0, 0, 0), alpha=110, blur=10):
    a = np.asarray(img.split()[3]).astype(np.float32) * alpha / 255
    pad = blur * 3
    sh = Image.new("L", (img.width + 2 * pad, img.height + 2 * pad), 0)
    sh.paste(Image.fromarray(a.astype(np.uint8)), (pad, pad + 8))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    layer = Image.new("RGBA", sh.size, color + (255,))
    layer.putalpha(sh)
    canvas.alpha_composite(layer, (x - pad, y - pad))
    canvas.alpha_composite(img, (x, y))


def panels(base, seam, size=80, gap=3, jitter=6, seed=1):
    """A wall of square test-chamber panels with a little tone variation."""
    rng = np.random.default_rng(seed)
    img = Image.new("RGBA", (W, H), seam + (255,))
    d = ImageDraw.Draw(img)
    for y in range(-size // 2, H, size):
        for x in range(-size // 3, W, size):
            v = int(rng.integers(-jitter, jitter + 1))
            c = tuple(int(np.clip(k + v, 0, 255)) for k in base)
            d.rectangle([x + gap, y + gap, x + size - gap, y + size - gap], fill=c + (255,))
    return img


def vignette(canvas, strength, color=(0, 0, 0)):
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot((xx - W * 0.6) / W, (yy - H / 2) / H)
    a = np.clip(r * strength * 255, 0, 255).astype(np.uint8)
    layer = Image.new("RGBA", (W, H), color + (255,))
    layer.putalpha(Image.fromarray(a))
    canvas.alpha_composite(layer)


def text_fade(canvas, color, alpha):
    """Soften the panels behind the title so the seams don't cut through it."""
    xx = np.tile(np.arange(W), (H, 1))
    a = np.clip(1 - (xx - 260) / 90, 0, 1) * alpha
    layer = Image.new("RGBA", (W, H), color + (255,))
    layer.putalpha(Image.fromarray(a.astype(np.uint8)))
    canvas.alpha_composite(layer)


def glow(canvas, x, y, radius, color, alpha):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([x - radius, y - radius, x + radius, y + radius],
                                  fill=color + (alpha,))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius / 2)))


def title(canvas, x, y, fg, sub_fg, lines):
    d = ImageDraw.Draw(canvas)
    big = ImageFont.truetype(BOLD, 50)
    sub = ImageFont.truetype(REGULAR, 19)
    d.text((x, y), "PORTAL", font=big, fill=fg)
    d.text((x, y + 50), "TURRET", font=big, fill=fg)
    d.rectangle([x + 2, y + 116, x + 54, y + 120], fill=RED)
    for i, line in enumerate(lines):
        d.text((x + 2, y + 134 + i * 25), line, font=sub, fill=sub_fg)


def banner_dark():
    canvas = panels((34, 34, 38), (14, 14, 16))
    vignette(canvas, 1.3)
    text_fade(canvas, (16, 16, 18), 170)
    emery = framed_emery(shot("emery-turret.png").resize((166, 189), Image.LANCZOS))
    gabbro = framed_gabbro(shot("gabbro-eye.png").resize((176, 176), Image.LANCZOS))
    ex, ey = 330, (H - emery.height) // 2 - 4
    gx, gy = W - gabbro.width - 18, (H - gabbro.height) // 2 + 8
    glow(canvas, gx + gabbro.width // 2, gy + gabbro.height // 2, 120, (200, 0, 0), 70)
    paste_with_shadow(canvas, emery, ex, ey)
    paste_with_shadow(canvas, gabbro, gx, gy)
    title(canvas, 34, 58, (240, 240, 240), (185, 185, 190),
          ["Its eye tells the time.", "Flick your wrist and", "it comes looking for you."])
    return canvas.convert("RGB")


def banner_light():
    canvas = panels((232, 232, 228), (150, 150, 150), jitter=4, seed=3)
    vignette(canvas, 0.45, (60, 60, 60))
    text_fade(canvas, (236, 236, 233), 225)
    emery = framed_emery(shot("emery-eye.png").resize((166, 189), Image.LANCZOS))
    gabbro = framed_gabbro(shot("gabbro-chamber.png").resize((176, 176), Image.LANCZOS))
    ex, ey = 330, (H - emery.height) // 2 - 4
    gx, gy = W - gabbro.width - 18, (H - gabbro.height) // 2 + 8
    paste_with_shadow(canvas, emery, ex, ey, alpha=90)
    paste_with_shadow(canvas, gabbro, gx, gy, alpha=90)
    title(canvas, 34, 58, (40, 40, 44), (80, 80, 86),
          ["The Portal turret for", "Pebble Time 2 and Round 2.", "Are you still there?"])
    return canvas.convert("RGB")


def main():
    banner_dark().save(STORE / "banner-dark.png")
    banner_light().save(STORE / "banner-light.png")
    for f in sorted(STORE.rglob("*.png")) + sorted(STORE.rglob("*.gif")):
        with Image.open(f) as im:
            print(f"{f.relative_to(ROOT)}: {im.size[0]}x{im.size[1]}, {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
