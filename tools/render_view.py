"""Render the zoomed-out turret, as the watch shows it, into a transparent PNG
for the phone settings page, along with the camera the page needs to draw the
room around it in the same perspective.

usage: render_view.py resources/turret.bin src/pkjs/turret_view.js

The camera matches setup_camera() in src/c/main.c fully zoomed out with no
sway (emery layout), framed on the page to everything the watch can show of the room while it
sways (both watches).
"""
import base64
import io
import json
import math
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

W = 360                # page canvas width, CSS pixels (height follows the view)
SS = 4                 # supersampling for the turret picture
OUT_SCALE = 2          # the PNG is 2x the canvas, for sharp phone screens


def load(path):
    b = open(path, 'rb').read()
    nv, nt = struct.unpack_from('<HH', b, 4)
    vscale, = struct.unpack_from('<f', b, 12)
    center = struct.unpack_from('<3f', b, 16)
    height, width = struct.unpack_from('<2f', b, 28)
    eye = struct.unpack_from('<3f', b, 36)
    eye_r, = struct.unpack_from('<f', b, 48)
    pal = np.frombuffer(b, np.uint8, 64, 100).reshape(16, 4)
    p = 164
    v = np.frombuffer(b, np.int16, nv * 3, p).reshape(-1, 3) * vscale
    p += nv * 6
    t = np.frombuffer(b, np.uint8, nt * 8, p).reshape(-1, 8)
    f = t[:, :6].copy().view(np.uint16).reshape(-1, 3).astype(int)
    hdr = dict(center=center, height=height, width=width, eye=eye, eye_r=eye_r)
    return hdr, v, f, t[:, 6], t[:, 7] & 1, pal


# the room, as in render_room() in src/c/main.c
WALL_Z, PANEL, TILE, NEAR = -1.25, 0.9, 0.45, 1.6
ROOM_X0, ROOM_X1, WALL_TOP = -4.5 * PANEL, 3.5 * PANEL, 4 * PANEL
YAW_MAX = math.radians(20)
PITCH = math.radians(12)


def watch_camera(hdr, w, h, round_):
    if round_:
        s1 = min(w, h) * 0.45 / math.hypot(hdr['height'] / 2, hdr['width'] / 2)
    else:
        s1 = min(h * 0.80 / hdr['height'], w * 0.90 / hdr['width'])
    c = hdr['center']
    return dict(scale=s1, tx=c[0], ty=c[1] - 0.07 * hdr['height'], tz=c[2],
                dist=hdr['height'] * 2.5, pitch=PITCH, cx=w / 2, cy=h / 2)


def room_hits(hdr, cam, w, h, round_, yaw):
    """Room points (model space) seen through each watch pixel at this sway."""
    ys, xs = np.mgrid[0:h:2, 0:w:2].astype(float)
    xs, ys = xs.ravel() + 0.5, ys.ravel() + 0.5
    if round_:
        keep = np.hypot(xs - w / 2, ys - h / 2) < min(w, h) / 2
        xs, ys = xs[keep], ys[keep]
    a = (xs - cam['cx']) / (cam['scale'] * cam['dist'])
    b = -(ys - cam['cy']) / (cam['scale'] * cam['dist'])
    cp, sp = math.cos(cam['pitch']), math.sin(cam['pitch'])
    # tilted camera space: point(t) = (a t, b t, dist - t); untilt, then unyaw
    def at(t):
        px, py, pz = a * t, b * t, cam['dist'] - t
        dx, dy, dz = px, py * cp + pz * sp, -py * sp + pz * cp
        X, Y, Z = cam['tx'] + dx, cam['ty'] + dy, cam['tz'] + dz
        cx, cz = hdr['center'][0], hdr['center'][2]
        ddx, ddz = X - cx, Z - cz
        # yaw_q: x' = c + dx cos + dz sin, z' = c + dz cos - dx sin; invert
        cy_, sy_ = math.cos(yaw), math.sin(yaw)
        return cx + ddx * cy_ - ddz * sy_, Y, cz + ddz * cy_ + ddx * sy_
    x0, y0, z0 = at(0.0)
    x1, y1, z1 = at(1.0)
    dxt, dyt, dzt = x1 - x0, y1 - y0, z1 - z0
    pts = []
    with np.errstate(divide='ignore', invalid='ignore'):
        tw = (WALL_Z - z0) / dzt          # wall plane
        tf = -y0 / dyt                    # floor plane
    for t, on_wall in ((tw, True), (tf, False)):
        X, Y, Z = x0 + dxt * t, y0 + dyt * t, z0 + dzt * t
        ok = (t > 0) & (X >= ROOM_X0) & (X <= ROOM_X1)
        if on_wall:
            ok &= (Y >= -1e-3) & (Y <= WALL_TOP)
        else:
            ok &= (Z >= WALL_Z - 1e-3) & (Z <= NEAR)
        pts.append((t, np.stack([X, Y, Z], 1), ok))
    (t1, p1, ok1), (t2, p2, ok2) = pts
    first_wall = ok1 & (~ok2 | (t1 < t2))
    first_floor = ok2 & ~first_wall
    return np.concatenate([p1[first_wall], p2[first_floor]])


def camera(hdr):
    """Phone camera: same angle as the watch, framed to everything either
    watch can show of the room at any sway."""
    hits = []
    for w, h, rnd in ((200, 228, False), (260, 260, True)):
        wc = watch_camera(hdr, w, h, rnd)
        for yaw in np.linspace(-YAW_MAX, YAW_MAX, 9):
            hits.append(room_hits(hdr, wc, w, h, rnd, yaw))
    hits = np.concatenate(hits)
    cam = watch_camera(hdr, 1, 1, False)
    cam.update(scale=1.0, cx=0.0, cy=0.0)
    uv, _ = project(cam, hits)
    umin, vmin = uv.min(0)
    umax, vmax = uv.max(0)
    scale = W / (umax - umin)
    h = int(math.ceil((vmax - vmin) * scale))
    cam.update(scale=scale, cx=-umin * scale, cy=-vmin * scale)
    return cam, h


def project(cam, p, k=1.0):
    p = np.atleast_2d(p)
    dy, dz = p[:, 1] - cam['ty'], p[:, 2] - cam['tz']
    cp, sp = math.cos(cam['pitch']), math.sin(cam['pitch'])
    py = dy * cp - dz * sp
    dz2 = dz * cp + dy * sp
    zc = cam['dist'] - dz2
    f = cam['scale'] * cam['dist'] / zc
    return np.stack([(cam['cx'] + (p[:, 0] - cam['tx']) * f) * k,
                     (cam['cy'] - py * f) * k], 1), zc


def main():
    hdr, v, f, col, two, pal = load(sys.argv[1])
    cam, H = camera(hdr)
    k = OUT_SCALE * SS
    scr, zc = project(cam, v, k)
    img = Image.new('RGBA', (W * k, H * k), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    L = np.array([-90, 150, 180]) / 256.0
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    # light is in camera space; the camera only pitches a little, ignore it
    for i in np.argsort(-zc[f].mean(1)):
        s = scr[f[i]]
        cross = (s[1, 0] - s[0, 0]) * (s[2, 1] - s[0, 1]) - (s[1, 1] - s[0, 1]) * (s[2, 0] - s[0, 0])
        nn = n[i]
        if cross >= 0:  # facing away (screen y points down)
            if not two[i]:
                continue
        if nn[2] < 0:
            nn = -nn
        cc = pal[col[i]]
        inten = 1.0 if cc[3] & 1 else (90 + max(0, nn @ L) * 190) / 256
        rgb = tuple(int(x) for x in np.clip(cc[:3] * inten, 0, 255))
        dr.polygon([tuple(q) for q in s], fill=rgb + (255,))

    # the eye: housing and red lens
    e, er = np.array(hdr['eye']), hdr['eye_r']
    (ex, ey), = project(cam, e, k)[0]
    (rx, _), = project(cam, e + [er, 0, 0], k)[0]
    r = rx - ex
    for rr, c in ((1.22, (170, 170, 170)), (1.0, (40, 40, 40)), (0.9, (0, 0, 0)), (0.75, (200, 0, 0)), (0.35, (0, 0, 0))):
        dr.ellipse([ex - r * rr, ey - r * rr, ex + r * rr, ey + r * rr], fill=c + (255,))

    img = img.resize((W * OUT_SCALE, H * OUT_SCALE), Image.LANCZOS)
    # bounding box crop is left to the page; a small palette keeps the PNG small
    img = img.quantize(64, method=Image.Quantize.FASTOCTREE)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    png = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    view = dict(w=W, h=H, cam=cam, eye=[ex / k, ey / k])
    with open(sys.argv[2], 'w') as out:
        out.write('// Generated by tools/render_view.py: the turret as the watch shows it\n')
        out.write('// zoomed out, and the camera to draw the room around it.\n')
        out.write('module.exports = ' + json.dumps(view) + ';\n')
        out.write('module.exports.png = ' + json.dumps(png) + ';\n')
    print(f'png {len(buf.getvalue())} bytes')


if __name__ == '__main__':
    main()
