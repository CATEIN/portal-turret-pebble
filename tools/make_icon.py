#!/usr/bin/env python3
"""The turret icon, rendered from the model: the body and open side panels,
straight on, centred on the eye (the legs and antenna would make it too thin
to read at menu size), on transparency.

usage: python3 tools/make_icon.py   (needs numpy and Pillow)

Outputs:
  resources/images/menu_icon.png   25x25, the watch's watchface menu icon
  store/icon-large.png             144x144
  store/icon-small.png             48x48
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import render_view

ROOT = Path(__file__).resolve().parent.parent
SS = 8  # supersampling


def render(size, eye_scale):
    hdr, v, f, col, two, pal = render_view.load(ROOT / "resources" / "turret.bin")
    S = size * SS
    lo, hi = v.min(0), v.max(0)
    side = (hi[0] - lo[0]) * 1.5
    cx, cy = (lo[0] + hi[0]) / 2, hdr["eye"][1] + 0.06 * side
    sc = S / side
    scr = np.stack([S / 2 + (v[:, 0] - cx) * sc, S / 2 - (v[:, 1] - cy) * sc], 1)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    light = np.array([-90, 150, 180]) / 256.0
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    for i in np.argsort(tri[:, :, 2].mean(1)):  # far first
        nn = n[i]
        if nn[2] < 0:
            if not two[i]:
                continue
            nn = -nn
        c = pal[col[i]]
        inten = 1.0 if c[3] & 1 else (90 + max(0, nn @ light) * 190) / 256
        rgb = tuple(int(x) for x in np.clip(c[:3] * inten, 0, 255))
        dr.polygon([tuple(q) for q in scr[f[i]]], fill=rgb + (255,))
    # the eye, enlarged at small sizes so it still reads
    e = np.array(hdr["eye"])
    er = hdr["eye_r"] * sc * eye_scale
    ex, ey = S / 2 + (e[0] - cx) * sc, S / 2 - (e[1] - cy) * sc
    for rr, c in ((1.25, (150, 150, 150)), (1.0, (20, 20, 20)), (0.8, (255, 30, 20)), (0.3, (20, 20, 20))):
        dr.ellipse([ex - er * rr, ey - er * rr, ex + er * rr, ey + er * rr], fill=c + (255,))
    return img.resize((size, size), Image.LANCZOS)


def main():
    (ROOT / "resources" / "images").mkdir(exist_ok=True)
    render(25, 2.0).save(ROOT / "resources" / "images" / "menu_icon.png")
    render(144, 1.3).save(ROOT / "store" / "icon-large.png")
    render(48, 1.6).save(ROOT / "store" / "icon-small.png")


if __name__ == "__main__":
    main()
