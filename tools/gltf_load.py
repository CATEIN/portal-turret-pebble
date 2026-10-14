"""Load the Sketchfab Portal Turret glTF, apply its skin in the rest pose,
and return world-space triangles with per-face colour, bone group and
outward normal (from the authored vertex normals).

Groups: 0 = body, 1 = left wing (+guns), 2 = right wing (+guns), 3 = eye.
"""
import json
import os

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

COMP_DTYPE = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
              5125: np.uint32, 5126: np.float32}
TYPE_N = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def quat_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def local_matrix(node):
    if 'matrix' in node:
        return np.array(node['matrix'], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    s = np.array(node.get('scale', [1, 1, 1]))
    m[:3, :3] = quat_mat(node.get('rotation', [0, 0, 0, 1])) * s
    m[:3, 3] = node.get('translation', [0, 0, 0])
    return m


def load(path):
    base = os.path.dirname(path)
    g = json.load(open(path))
    bin_data = open(os.path.join(base, g['buffers'][0]['uri']), 'rb').read()

    def acc(i):
        a = g['accessors'][i]
        bv = g['bufferViews'][a['bufferView']]
        dt = COMP_DTYPE[a['componentType']]
        n = TYPE_N[a['type']]
        off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        stride = bv.get('byteStride', 0)
        isz = np.dtype(dt).itemsize * n
        if stride and stride != isz:
            raw = np.frombuffer(bin_data, np.uint8, a['count'] * stride, off)
            raw = raw.reshape(a['count'], stride)[:, :isz].copy()
            arr = raw.view(dt)
        else:
            arr = np.frombuffer(bin_data, dt, a['count'] * n, off)
        return arr.reshape(a['count'], n) if n > 1 else arr

    nodes = g['nodes']
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get('children', []):
            parent[c] = i
    world = {}

    def wm(i):
        if i not in world:
            m = local_matrix(nodes[i])
            world[i] = wm(parent[i]) @ m if i in parent else m
        return world[i]

    skin = g['skins'][0]
    joints = skin['joints']
    ibm = acc(skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
    joint_mats = np.array([wm(j) @ ibm[k] for k, j in enumerate(joints)])
    names = [nodes[j].get('name', '') for k, j in enumerate(joints)]

    def joint_group(name):
        if name.startswith('LFT_'):
            return 1
        if name.startswith('RT_'):
            return 2
        if name.startswith('eyeball'):
            return 3
        return 0
    jgroup = np.array([joint_group(n) for n in names])

    tex = np.asarray(Image.open(os.path.join(base, 'textures/Turret_baseColor.png')).convert('RGB'))
    emi = np.asarray(Image.open(os.path.join(base, 'textures/Turret_emissive.png')).convert('RGB'))
    th, tw = tex.shape[:2]

    def sample(img, uv):
        u = np.mod(uv[:, 0], 1.0)
        v = np.mod(uv[:, 1], 1.0)
        x = np.clip((u * img.shape[1]).astype(int), 0, img.shape[1] - 1)
        y = np.clip((v * img.shape[0]).astype(int), 0, img.shape[0] - 1)
        return img[y, x].astype(np.float32)

    all_v, all_f, all_col, all_emi, all_grp, all_n = [], [], [], [], [], []
    voff = 0
    for ni, n in enumerate(nodes):
        if 'mesh' not in n:
            continue
        for prim in g['meshes'][n['mesh']]['primitives']:
            at = prim['attributes']
            pos = acc(at['POSITION']).astype(np.float64)
            nrm = acc(at['NORMAL']).astype(np.float64)
            uv = acc(at['TEXCOORD_0']).astype(np.float64)
            jn = acc(at['JOINTS_0']).astype(int)
            wt = acc(at['WEIGHTS_0']).astype(np.float64)
            idx = acc(prim['indices']).astype(int).reshape(-1, 3)

            ph = np.c_[pos, np.ones(len(pos))]
            skinned = np.zeros((len(pos), 4))
            snrm = np.zeros((len(pos), 3))
            for k in range(4):
                m = joint_mats[jn[:, k]]
                skinned += wt[:, k:k + 1] * np.einsum('nij,nj->ni', m, ph)
                snrm += wt[:, k:k + 1] * np.einsum('nij,nj->ni', m[:, :3, :3], nrm)
            v = skinned[:, :3]

            dom = jn[np.arange(len(jn)), np.argmax(wt, axis=1)]
            vgrp = jgroup[dom]

            # face colour: average of centroid and the three corners pulled
            # slightly towards the centroid (avoids bleeding across UV seams)
            tuv = uv[idx]                       # (F, 3, 2)
            cuv = tuv.mean(axis=1)
            samples = [sample(tex, cuv)]
            esamples = [sample(emi, cuv)]
            for c in range(3):
                p = cuv + (tuv[:, c] - cuv) * 0.6
                samples.append(sample(tex, p))
                esamples.append(sample(emi, p))
            col = np.mean(samples, axis=0)
            em = np.mean(esamples, axis=0)

            # face group = majority of its vertices' groups
            fg = vgrp[idx]
            fgrp = np.array([np.bincount(r, minlength=4).argmax() for r in fg])

            all_v.append(v)
            all_f.append(idx + voff)
            all_col.append(col)
            all_emi.append(em)
            all_grp.append(fgrp)
            all_n.append(snrm[idx].mean(axis=1))
            voff += len(v)

    return (np.concatenate(all_v), np.concatenate(all_f), np.concatenate(all_col),
            np.concatenate(all_emi), np.concatenate(all_grp), np.concatenate(all_n))
