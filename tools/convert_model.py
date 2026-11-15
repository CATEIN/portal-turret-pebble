"""Convert a Sketchfab turret glTF ("Portal Turret" by Igrium, CC-BY-4.0, or
"Defective Turret - From Portal 2 (Original)" by David & 3D, CC-BY-NC-4.0)
into the compact binary mesh read by src/c/main.c.

usage: convert_model.py path/to/scene.gltf resources/turret.bin [target_tris] [--profile NAME]
                        [--legs Y]

NAME is a profile in tools/models.py (default: turret). --legs simplifies the
body below height Y (the legs) on its own, so a light mesh doesn't lose them.

The regular turret is symmetric about x = 0, so only its left half is stored,
and the watch mirrors it (flag FLAG_MIRROR); parts that don't mirror (the
antenna) are stored whole. target_tris counts the triangles drawn, both halves.

Needs numpy, pillow and fast-simplification.
"""
import struct
import sys

import fast_simplification
import numpy as np

import gltf_load
import models

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
PROFILE = sys.argv[sys.argv.index('--profile') + 1] if '--profile' in sys.argv else 'turret'
if PROFILE in ARGS:
    ARGS.remove(PROFILE)
LEGS = float(sys.argv[sys.argv.index('--legs') + 1]) if '--legs' in sys.argv else None
if LEGS is not None:
    ARGS.remove(sys.argv[sys.argv.index('--legs') + 1])
TARGET_TRIS = int(ARGS[2]) if len(ARGS) > 2 else 1800
MIRROR = models.PROFILES[PROFILE]['mirror']
UNIQUE_ABOVE = models.PROFILES[PROFILE]['unique_above']
WING_CLOSE = models.PROFILES[PROFILE]['wing_close']  # how far each side panel slides in when closed
GAIN = models.PROFILES[PROFILE]['gain']
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


def asymmetric_verts(v, rel=0.01):
    """Vertices whose mirror image (x -> -x) isn't on the model."""
    m = v * [-1, 1, 1]
    d = np.empty(len(v))
    for s in range(0, len(v), 1000):
        d[s:s + 1000] = np.sqrt(((m[s:s + 1000, None] - v[None]) ** 2).sum(-1)).min(1)
    return d > rel * (v[:, 1].max() - v[:, 1].min())


def clip_left(v, f):
    """Cut the faces at x = 0 and keep the x <= 0 side. Returns the vertices
    (new ones on the cut appended), the faces, and each face's source face."""
    v = list(map(tuple, v))
    out_f, src = [], []
    cut = {}

    def on_cut(a, b):
        key = (min(a, b), max(a, b))
        if key not in cut:
            pa, pb = np.array(v[a]), np.array(v[b])
            t = pa[0] / (pa[0] - pb[0])
            p = pa + (pb - pa) * t
            p[0] = 0.0
            cut[key] = len(v)
            v.append(tuple(p))
        return cut[key]

    for i, tri in enumerate(f):
        side = [np.sign(v[k][0]) for k in tri]   # points on the cut count on both sides
        if max(side) <= 0:
            out_f.append(list(tri)); src.append(i)
            continue
        if min(side) >= 0:
            continue
        # walk the edges, keeping the inside part (a triangle or a quad)
        poly = []
        for j in range(3):
            a, b = tri[j], tri[(j + 1) % 3]
            if side[j] <= 0:
                poly.append(a)
            if side[j] * side[(j + 1) % 3] < 0:
                poly.append(on_cut(a, b))
        for j in range(1, len(poly) - 1):
            out_f.append([poly[0], poly[j], poly[j + 1]]); src.append(i)
    return np.array(v), np.array(out_f, int), np.array(src, int)




def main():
    src, dst = ARGS[0], ARGS[1]
    v, f, col, emi, grp, fnorm = gltf_load.load(src)
    vpanel = np.zeros(len(v), int)
    for gi in (1, 2):
        vpanel[np.unique(f[grp == gi])] = gi
    v = models.apply(PROFILE, v, vpanel)

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

    # what doesn't mirror is kept whole; of the rest, the right side panel
    # goes (it's the left one mirrored), and the body is cut down the middle
    # once it's simplified
    if MIRROR:
        asym = asymmetric_verts(v)[f].any(1)
        unique = asym & (v[f].mean(1)[:, 1] > UNIQUE_ABOVE) if UNIQUE_ABOVE else np.zeros(len(f), bool)
        keep = unique | (grp != 2)
        f, col, emi, grp, is_eye, fnorm, unique = (a[keep] for a in (f, col, emi, grp, is_eye, fnorm, unique))
        print(f'mirrored: {(~unique).sum()} faces, stored whole: {unique.sum()}')
    else:
        unique = np.ones(len(f), bool)

    # simplify each group separately so panels stay separate parts
    out_v, out_f, out_col, out_grp, out_vg, out_half = [], [], [], [], [], []
    centroids = v[f].mean(1)
    total = len(f) + ((grp == 1) & ~unique).sum()   # faces drawn (the left panel twice)
    # the main part (the half, or the whole model) in groups, legs on their
    # own if asked; then what's stored whole besides the half
    main = ~unique if MIRROR else unique
    parts = [(gi, (grp == gi) & main) for gi in range(3)]
    if LEGS is not None:
        low = centroids[:, 1] < LEGS
        parts = [(0, parts[0][1] & ~low), (0, parts[0][1] & low)] + parts[1:]
    parts = [(gi, m) for gi, m in parts if m.any()]
    if MIRROR:
        parts += [(gi, (grp == gi) & unique) for gi in range(3) if ((grp == gi) & unique).any()]
    for gi, m in parts:
        half = not unique[m][0]
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
        want = min(len(gf), max(60, int(TARGET_TRIS * m.sum() / total)))
        target = want
        for _ in range(4):
            reduction = 1.0 - target / len(gf)
            if reduction > 0:
                sv, sf = fast_simplification.simplify(gv, gf, target_reduction=reduction, agg=7)
            else:
                sv, sf = gv, gf
            if not (half and gi == 0):
                break
            # the body: keep its left half. Cut after simplifying, so the cut
            # edge lies exactly on x = 0 and meets its mirror image. Cutting
            # splits the faces across the middle, so aim lower until the two
            # halves come to the faces wanted
            sv, sf, _ = clip_left(sv, sf)
            used, inv = np.unique(sf, return_inverse=True)
            sv, sf = sv[used], inv.reshape(-1, 3)
            if 2 * len(sf) <= want * 1.02:
                break
            target = int(target * want / (2 * len(sf)))
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
        out_half.append(half)
        print(f'group {gi}{" half" if half else ""}: {len(gf)} -> {len(sf)} tris, {len(sv)} verts')

    # stored: the half's parts, then the whole ones; the watch appends the
    # mirrored half (the same order is built here to work on the full model)
    order = [i for i in range(len(out_v)) if out_half[i]] + [i for i in range(len(out_v)) if not out_half[i]]
    vs, fs, cs, vgs = [], [], [], []
    base = 0
    for i in order:
        fs.append(out_f[i] - sum(len(out_v[j]) for j in range(i)) + base)
        vs.append(out_v[i]); cs.append(out_col[i]); vgs.append(out_vg[i])
        base += len(out_v[i])
    nh = sum(len(out_v[i]) for i in order if out_half[i])     # mirrored verts
    th = sum(len(out_f[i]) for i in order if out_half[i])     # mirrored tris
    v_st = np.concatenate(vs)
    f_st = np.concatenate(fs).astype(int)
    col_st = np.concatenate(cs).astype(np.float64)
    vg_st = np.concatenate(vgs)
    ns = len(v_st)
    v = np.concatenate([v_st, v_st[:nh] * [-1, 1, 1]])
    f = np.concatenate([f_st, f_st[:th, ::-1] + ns])
    col = np.concatenate([col_st, col_st[:th]])
    vg = np.concatenate([vg_st, np.choose(vg_st[:nh], [0, 2, 1, 3])])

    # palette: k-means on face colours; keep the eye red as its own entry
    eye_face = (col[:, 0] > 200) & (col[:, 1] < 80)
    cent, lab = kmeans(col[~eye_face], NPAL)
    pal_idx = np.empty(len(f), int)
    pal_idx[~eye_face] = lab
    pal_idx[eye_face] = NPAL
    pal = [(*np.clip(c, 0, 255).astype(int), 0) for c in cent] + [(255, 30, 0, 1)]
    # The texture is darker than the in-game look; brighten the shell a bit
    pal = [(min(255, int(r * GAIN)), min(255, int(g * GAIN)), min(255, int(b * GAIN)), fl)
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
    # a mirrored face is its half's face, so decide on the pair together
    m = slice(len(f_st), None)
    fr[:th] += fr[m]; bk[:th] += bk[m]
    fr[m], bk[m] = fr[:th], bk[:th]
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
    vq = np.round(v[:ns] / vscale).astype(np.int16)

    group_off = np.zeros((MAX_GROUPS, 3))
    group_off[1] = [-WING_CLOSE, 0, 0]   # left panel opens towards -x
    group_off[2] = [WING_CLOSE, 0, 0]

    flags = 3 if MIRROR else 1  # cull, mirror
    hdr = struct.pack('<4sHHBBH', b'TRT1', len(v), len(f), 3, len(pal), flags)
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
    if MIRROR:
        hdr += struct.pack('<HH', nh, th)  # how much of the start mirrors

    nt = len(f_st)
    body = vq.tobytes()
    for t, p, ds in zip(f[:nt], pal_idx[:nt], two_sided[:nt]):
        body += struct.pack('<3HBB', t[0], t[1], t[2], p, 1 if ds else 0)
    body += n8[:nt].tobytes()
    body += vg[:ns].astype(np.uint8).tobytes()

    open(dst, 'wb').write(hdr + body)
    print(f'{len(v)} verts, {len(f)} tris drawn; stored {ns} verts, {nt} tris, '
          f'{len(hdr) + len(body)} bytes')
    print('eye', eye_c, eye_r, 'center', center, 'h', height, 'w', width)
    print('palette', pal)


if __name__ == '__main__':
    main()
