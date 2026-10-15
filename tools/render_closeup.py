#!/usr/bin/env python3
"""Render the close-up background: the original (full detail, textured,
smoothly shaded) turret model exactly as the watch's close-up camera sees it,
so the eye view has no low-poly facets. The watch shows this picture behind
the eye and dissolves into its own low-poly model as it zooms out.

usage: render_closeup.py model/scene.gltf resources/turret.bin resources/closeup
           [--profile NAME] [--preview DIR]

Writes resources/closeup~emery.bin and closeup~gabbro.bin (one resource,
a file per platform; the last argument is the name before the ~). NAME is a
profile in tools/models.py (default: turret). Each file:
  u16 width, u16 height, a 16-entry palette of Pebble colour bytes (0b11rrggbb;
  entry 0 is 0 = nothing drawn there), then 4 bits per pixel, rows of
  (width + 1) / 2 bytes, the left pixel in the low nibble. The picture is
  dithered with the watch's 4x4 pattern; it only uses ~16 colours.

The camera matches setup_camera() in src/c/main.c at zoom 0 (EYE_PX, no sway
or tilt, side panels closed); the light and the shell brightening match the
watch's renderer and tools/convert_model.py.
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import gltf_load
import models

PLATFORMS = {"emery": (200, 228, 74.0), "gabbro": (260, 260, 76.0)}  # w, h, EYE_PX
SS = 4                      # supersampling
LIGHT = np.array([-90, 150, 180], float)
AMBIENT, DIFFUSE = 90 / 256, 190 / 256
BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]])


def header(path):
    b = open(path, "rb").read()
    height, = struct.unpack_from("<f", b, 28)
    eye = np.array(struct.unpack_from("<3f", b, 36))
    eye_r, = struct.unpack_from("<f", b, 48)
    return height, eye, eye_r


def sample(img, uv):
    """Bilinear texture lookup, uv in [0, 1) (wrapped), returns float RGB."""
    h, w = img.shape[:2]
    x = np.mod(uv[:, 0], 1.0) * w - 0.5
    y = np.mod(uv[:, 1], 1.0) * h - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    x0, y0 = np.mod(x0, w), np.mod(y0, h)
    x1, y1 = np.mod(x0 + 1, w), np.mod(y0 + 1, h)
    img = img.astype(np.float32)
    top = img[y0, x0] * (1 - fx) + img[y0, x1] * fx
    bot = img[y1, x0] * (1 - fx) + img[y1, x1] * fx
    return top * (1 - fy) + bot * fy


def render(mesh, profile, height, eye, eye_r, w, h, eye_px):
    p = models.PROFILES[profile]
    v = models.apply(profile, mesh["v"], mesh["vgrp"])
    v[mesh["vgrp"] == 1, 0] += p["wing_close"]      # panels closed, as in the close-up
    v[mesh["vgrp"] == 2, 0] -= p["wing_close"]
    f, uv, vn = mesh["f"], mesh["uv"], mesh["vn"]

    scale = eye_px / eye_r
    dist = height * 2.5
    zc = dist - (v[:, 2] - eye[2])
    k = scale * dist / zc
    sx = (w / 2 + (v[:, 0] - eye[0]) * k) * SS
    sy = (h / 2 - (v[:, 1] - eye[1]) * k) * SS
    W, H = w * SS, h * SS

    depth = np.full((H, W), np.inf)
    tri_id = np.full((H, W), -1)
    bary = np.zeros((H, W, 3))
    for t, (a, b, c) in enumerate(f):
        xs, ys = sx[[a, b, c]], sy[[a, b, c]]
        x0, x1 = int(max(0, np.floor(xs.min()))), int(min(W - 1, np.ceil(xs.max())))
        y0, y1 = int(max(0, np.floor(ys.min()))), int(min(H - 1, np.ceil(ys.max())))
        if x0 > x1 or y0 > y1 or min(zc[[a, b, c]]) <= 0:
            continue
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-12:
            continue
        py, px = np.mgrid[y0:y1 + 1, x0:x1 + 1] + 0.5
        l0 = ((ys[1] - ys[2]) * (px - xs[2]) + (xs[2] - xs[1]) * (py - ys[2])) / den
        l1 = ((ys[2] - ys[0]) * (px - xs[2]) + (xs[0] - xs[2]) * (py - ys[2])) / den
        l2 = 1 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue
        # perspective-correct weights and depth
        iz = 1 / zc[[a, b, c]]
        w0, w1, w2 = l0 * iz[0], l1 * iz[1], l2 * iz[2]
        s = w0 + w1 + w2
        z = 1 / s
        region = depth[y0:y1 + 1, x0:x1 + 1]
        win = inside & (z < region)
        region[win] = z[win]
        tri_id[y0:y1 + 1, x0:x1 + 1][win] = t
        bb = np.stack([w0 / s, w1 / s, w2 / s], -1)
        bary[y0:y1 + 1, x0:x1 + 1][win] = bb[win]

    hit = tri_id >= 0
    ti = tri_id[hit]
    bw = bary[hit][:, :, None]
    fi = f[ti]
    puv = (uv[fi] * bw).sum(1)
    pn = (vn[fi] * bw).sum(1)
    pn /= np.linalg.norm(pn, axis=1, keepdims=True) + 1e-12

    # per material: textures (or flat factors), normal map if it has one
    fm = mesh["fmat"][ti]
    base = np.zeros((len(ti), 3), np.float32)
    emi = np.zeros((len(ti), 3), np.float32)
    nmap = np.zeros((len(ti), 3), np.float32)
    has_nmap = np.zeros(len(ti), bool)
    for k, mat in enumerate(mesh["mats"]):
        sel = fm == k
        if not sel.any():
            continue
        u = puv[sel]
        base[sel] = (sample(mat["base"], u) if mat["base"] is not None else 255.0) * mat["base_factor"]
        if mat["emissive"] is not None:
            emi[sel] = sample(mat["emissive"], u) * mat["emissive_factor"]
        else:
            emi[sel] = mat["emissive_factor"] * 255
        if mat["normal"] is not None:
            nmap[sel] = sample(mat["normal"], u) / 255 * 2 - 1
            has_nmap[sel] = True

    # normal map: per-triangle tangent frame from the UVs
    p0, p1, p2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    u0, u1, u2 = uv[f[:, 0]], uv[f[:, 1]], uv[f[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = u1 - u0, u2 - u0
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-12, 1e-12, r)
    tang = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / r[:, None]
    bitan = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / r[:, None]
    T = tang[ti] - pn * (tang[ti] * pn).sum(1, keepdims=True)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    B = bitan[ti] - pn * (bitan[ti] * pn).sum(1, keepdims=True) - T * (bitan[ti] * T).sum(1, keepdims=True)
    B /= np.linalg.norm(B, axis=1, keepdims=True) + 1e-12
    # glTF texture v runs down the image, so the map's green points along -B
    n = np.where(has_nmap[:, None], T * nmap[:, 0:1] - B * nmap[:, 1:2] + pn * nmap[:, 2:3], pn)
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    n[n[:, 2] < 0] *= -1   # seen from behind (thin parts): light the front

    light = AMBIENT + DIFFUSE * np.clip(n @ LIGHT, 0, None) / 256
    rgb = np.clip(base * p["gain"] * light[:, None] + emi, 0, 255)

    img = np.zeros((H, W, 3))
    img[hit] = rgb
    cover = hit.astype(float)
    # average the supersamples
    img = img.reshape(h, SS, w, SS, 3).sum((1, 3))
    cover = cover.reshape(h, SS, w, SS).sum((1, 3))
    filled = cover > SS * SS / 2
    img = img / np.maximum(cover, 1)[..., None]
    return img, filled


def to_pebble(img, filled):
    """Dither to the 64-colour palette with the watch's 4x4 pattern."""
    h, w = filled.shape
    lvl = img * 3 / 255
    lo = np.floor(lvl).astype(int)
    fr = ((lvl - lo) * 16).astype(int)
    thr = BAYER[np.arange(h)[:, None] % 4, np.arange(w)[None, :] % 4][..., None]
    q = np.clip(lo + (fr > thr), 0, 3)
    out = 0xC0 | (q[..., 0] << 4) | (q[..., 1] << 2) | q[..., 2]
    out[~filled] = 0
    return out.astype(np.uint8)


def pack4(px):
    """Palette of the 15 most used colours (+ 0 for empty), nearest for the rest."""
    vals, counts = np.unique(px[px != 0], return_counts=True)
    pal = [0] + [int(v) for v in vals[np.argsort(-counts)][:15]]
    pal += [0] * (16 - len(pal))
    rgb = lambda c: np.array([(c >> 4) & 3, (c >> 2) & 3, c & 3])
    lut = np.zeros(256, np.uint8)
    for v in vals:
        if int(v) in pal[1:]:
            lut[v] = pal.index(int(v), 1)
        else:  # nearest colour in the palette
            d = [np.abs(rgb(int(v)) - rgb(c)).sum() if c else 99 for c in pal]
            lut[v] = int(np.argmin(d))
    idx = lut[px]
    h, w = idx.shape
    if w % 2:
        idx = np.concatenate([idx, np.zeros((h, 1), np.uint8)], 1)
    packed = (idx[:, 0::2] | (idx[:, 1::2] << 4)).astype(np.uint8)
    return bytes(pal), packed.tobytes(), np.array(pal, np.uint8)[idx[:, :w]]


def preview(px):
    rgb = np.stack([(px >> 4) & 3, (px >> 2) & 3, px & 3], -1) * 85
    return Image.fromarray(rgb.astype(np.uint8))


def main():
    args = sys.argv[1:]
    prev_dir = profile = None
    if "--preview" in args:
        i = args.index("--preview")
        prev_dir = args[i + 1]
        del args[i:i + 2]
    profile = "turret"
    if "--profile" in args:
        i = args.index("--profile")
        profile = args[i + 1]
        del args[i:i + 2]
    gltf, model, out = args[:3]
    mesh = gltf_load.load(gltf, full=True)
    height, eye, eye_r = header(model)
    for name, (w, h, eye_px) in PLATFORMS.items():
        img, filled = render(mesh, profile, height, eye, eye_r, w, h, eye_px)
        px = to_pebble(img, filled)
        path = Path(f"{out}~{name}.bin")
        pal, packed, px = pack4(px)
        path.write_bytes(struct.pack("<HH", w, h) + pal + packed)
        print(f"{path}: {w}x{h}, {filled.mean() * 100:.0f}% covered")
        if prev_dir:
            preview(px).save(Path(prev_dir) / f"{Path(out).name}_{name}.png")


if __name__ == "__main__":
    main()
