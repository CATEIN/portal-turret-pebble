"""Convert the Sketchfab "Portal Turret" glTF (by Igrium, CC-BY-4.0) into the
compact binary mesh read by src/c/main.c.

usage: convert_model.py path/to/scene.gltf resources/turret.bin [target_tris]

Needs numpy, pillow and fast-simplification.
"""
import struct
import sys

import fast_simplification
import numpy as np

import gltf_load

TARGET_TRIS = int(sys.argv[3]) if len(sys.argv) > 3 else 1800
WING_CLOSE = 0.17     # how far each side panel slides in when closed
NPAL = 15             # palette entries for the shell (one more for the eye)
MAX_GROUPS = 4


def kmeans(x, k, iters=30, seed=1):
    rng = np.random.default_rng(seed)
    cent = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((x[:, None] - cent[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            if (lab == j).any():
                cent[j] = x[lab == j].mean(0)
    return cent, lab


def seen_sides(v, f, n_dirs=40, res=420):
    """Pixels of each face's front (counter-clockwise) and back side seen
    from n_dirs directions around the model (painter's-algorithm ID render)."""
    from PIL import Image, ImageDraw
    front = np.zeros(len(f), int)
    back = np.zeros(len(f), int)
    wn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    i = np.arange(n_dirs) + 0.5
    phi = np.arccos(1 - 2 * i / n_dirs)
    theta = np.pi * (1 + 5 ** 0.5) * i
    dirs = np.c_[np.cos(theta) * np.sin(phi), np.cos(phi), np.sin(theta) * np.sin(phi)]
    c = (v.min(0) + v.max(0)) / 2
    scale = res * 0.95 / np.linalg.norm(v.max(0) - v.min(0))
    for d in dirs:
        up = np.array([0, 1, 0]) if abs(d[1]) < 0.9 else np.array([1, 0, 0])
        r = np.cross(up, d); r /= np.linalg.norm(r)
        u = np.cross(d, r)
        p = (v - c) @ np.c_[r, u, d]
        tri = p[f]
        img = Image.new('RGB', (res, res), (255, 255, 255))
        dr = ImageDraw.Draw(img)
        for k in np.argsort(tri[:, :, 2].mean(1)):   # far (-d) first
            pts = [(res / 2 + q[0] * scale, res / 2 - q[1] * scale) for q in tri[k]]
            dr.polygon(pts, fill=(k & 255, (k >> 8) & 255, k >> 16))
        a = np.asarray(img).astype(np.int64)
        ids = a[..., 0] | (a[..., 1] << 8) | (a[..., 2] << 16)
        px = np.bincount(ids[ids < len(f)].ravel(), minlength=len(f))
        facing = wn @ d > 0
        front[facing] += px[facing]
        back[~facing] += px[~facing]
    return front, back


def visible_faces(v, f):
    front, back = seen_sides(v, f)
    return (front + back) > 0


def main():
    src, dst = sys.argv[1], sys.argv[2]
    v, f, col, emi, grp, fnorm = gltf_load.load(src)

    # eye: the emissive faces
    is_eye = emi.max(1) > 40
    eye_pts = v[f[is_eye]].reshape(-1, 3)
    eye_c = (eye_pts.min(0) + eye_pts.max(0)) / 2
    eye_c[2] = eye_pts[:, 2].max()
    eye_r = (eye_pts[:, 0].max() - eye_pts[:, 0].min()) / 2 * 1.25

    # drop faces hidden inside the shell (seen with panels open or closed)
    vc = v.copy()
    for gi, sx in ((1, 1), (2, -1)):
        vc[np.unique(f[grp == gi]), 0] += sx * WING_CLOSE
    keep = visible_faces(v, f) | visible_faces(vc, f)
    print(f'visible faces: {keep.sum()} / {len(f)}')
    f, col, emi, grp, is_eye, fnorm = (f[keep], col[keep], emi[keep], grp[keep], is_eye[keep],
                                       fnorm[keep])

    # simplify each group separately so panels stay separate parts
    out_v, out_f, out_col, out_grp, out_vg = [], [], [], [], []
    centroids = v[f].mean(1)
    total = len(f)
    for gi in range(3):
        m = grp == gi
        gf = f[m]
        # weld vertices split at UV seams so the simplifier sees one surface
        key = np.round(v / 1e-4).astype(np.int64)
        _, weld = np.unique(key, axis=0, return_inverse=True)
        gf = weld.reshape(-1)[gf]
        gf = gf[(gf[:, 0] != gf[:, 1]) & (gf[:, 1] != gf[:, 2]) & (gf[:, 0] != gf[:, 2])]
        used, inv = np.unique(gf, return_inverse=True)
        gv = np.zeros((weld.max() + 1, 3))
        gv[weld.reshape(-1)] = v
        gv = gv[used]
        gf = inv.reshape(-1, 3)
        target = max(60, int(TARGET_TRIS * m.sum() / total))
        reduction = 1.0 - target / len(gf)
        if reduction > 0:
            sv, sf = fast_simplification.simplify(gv, gf, target_reduction=reduction, agg=7)
        else:
            sv, sf = gv, gf
        # colour each new face by averaging the nearest original faces at a
        # few points spread over it, so thin dark seams don't take over
        # whole triangles
        oc = centroids[m]
        ocol = np.where(is_eye[m, None], [255, 40, 0], col[m])
        st = sv[sf]
        bary = np.array([[1, 1, 1], [4, 1, 1], [1, 4, 1], [1, 1, 4],
                         [2, 2, 1], [2, 1, 2], [1, 2, 2]], float)
        bary /= bary.sum(1, keepdims=True)
        acc = np.zeros((len(sf), 3))
        for b in bary:
            pts = np.einsum('k,fkj->fj', b, st)
            for s in range(0, len(sf), 256):
                d = ((pts[s:s + 256, None] - oc[None]) ** 2).sum(-1)
                acc[s:s + 256] += ocol[np.argmin(d, axis=1)]
        fcol = acc / len(bary)
        # keep winding outward (the simplifier can flip a few faces): compare
        # with the authored normal of the nearest original face
        onrm = fnorm[m]
        cen = st.mean(1)
        near = np.empty(len(sf), int)
        for s in range(0, len(sf), 256):
            d = ((cen[s:s + 256, None] - oc[None]) ** 2).sum(-1)
            near[s:s + 256] = np.argmin(d, axis=1)
        wn = np.cross(st[:, 1] - st[:, 0], st[:, 2] - st[:, 0])
        flip = (wn * onrm[near]).sum(1) < 0
        sf = sf.copy()
        sf[flip] = sf[flip][:, ::-1]
        print(f'  flipped {flip.sum()} faces')
        # eye faces stay pure red rather than blended
        fcol[(fcol[:, 0] > 150) & (fcol[:, 1] < 90)] = [255, 40, 0]
        out_f.append(sf + sum(len(a) for a in out_v))
        out_v.append(sv)
        out_col.append(fcol)
        out_grp.append(np.full(len(sf), gi))
        out_vg.append(np.full(len(sv), gi))
        print(f'group {gi}: {len(gf)} -> {len(sf)} tris, {len(sv)} verts')

    v = np.concatenate(out_v)
    f = np.concatenate(out_f).astype(int)
    col = np.concatenate(out_col).astype(np.float64)
    vg = np.concatenate(out_vg)

    # palette: k-means on face colours; keep the eye red as its own entry
    eye_face = (col[:, 0] > 200) & (col[:, 1] < 80)
    cent, lab = kmeans(col[~eye_face], NPAL)
    pal_idx = np.empty(len(f), int)
    pal_idx[~eye_face] = lab
    pal_idx[eye_face] = NPAL
    pal = [(*np.clip(c, 0, 255).astype(int), 0) for c in cent] + [(255, 30, 0, 1)]
    # The texture is darker than the in-game look; brighten the shell a bit
    pal = [(min(255, int(r * 1.35)), min(255, int(g * 1.35)), min(255, int(b * 1.35)), fl)
           if fl == 0 else (r, g, b, fl) for r, g, b, fl in pal]

    # Fix winding from what is actually visible: faces only ever seen from
    # behind get flipped; faces seen from both sides (thin parts) are marked
    # double-sided so the watch never culls them.
    vc = v.copy()
    vc[vg == 1, 0] += WING_CLOSE
    vc[vg == 2, 0] -= WING_CLOSE
    fr1, bk1 = seen_sides(v, f, 60, 480)
    fr2, bk2 = seen_sides(vc, f, 60, 480)
    fr, bk = fr1 + fr2, bk1 + bk2
    flip = bk > 3 * fr
    f[flip] = f[flip][:, ::-1]
    fr[flip], bk[flip] = bk[flip], fr[flip]
    two_sided = (bk > 30) & (bk > fr // 4)
    print(f'winding: flipped {flip.sum()}, double-sided {two_sided.sum()}, '
          f'never seen {((fr + bk) == 0).sum()}')

    # face normals (from winding)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    n8 = np.clip(np.round(n * 127), -127, 127).astype(np.int8)

    # bounds with panels open
    lo, hi = v.min(0), v.max(0)
    center = (lo + hi) / 2
    height = hi[1] - lo[1]
    width = hi[0] - lo[0]

    vscale = np.abs(v).max() / 32000.0
    vq = np.round(v / vscale).astype(np.int16)

    group_off = np.zeros((MAX_GROUPS, 3))
    group_off[1] = [-WING_CLOSE, 0, 0]   # left panel opens towards -x
    group_off[2] = [WING_CLOSE, 0, 0]

    hdr = struct.pack('<4sHHBBH', b'TRT1', len(v), len(f), 3, len(pal), 1)  # flags: cull
    hdr += struct.pack('<f', vscale)
    hdr += struct.pack('<3f', *center)
    hdr += struct.pack('<ff', height, width)
    hdr += struct.pack('<3f', *eye_c)
    hdr += struct.pack('<f', eye_r)
    hdr += struct.pack('<12f', *group_off.flatten())
    palb = b''.join(struct.pack('<4B', *p) for p in pal)
    palb += b'\0' * (64 - len(palb))
    hdr += palb
    assert len(hdr) == 164, len(hdr)

    body = vq.tobytes()
    for t, p, ds in zip(f, pal_idx, two_sided):
        body += struct.pack('<3HBB', t[0], t[1], t[2], p, 1 if ds else 0)
    body += n8.tobytes()
    body += vg.astype(np.uint8).tobytes()

    open(dst, 'wb').write(hdr + body)
    print(f'{len(v)} verts, {len(f)} tris, {len(hdr) + len(body)} bytes')
    print('eye', eye_c, eye_r, 'center', center, 'h', height, 'w', width)
    print('palette', pal)


if __name__ == '__main__':
    main()
