"""Per-model settings shared by tools/convert_model.py and render_closeup.py.

Both turret models use Valve's turret skeleton (body, LFT_/RT_ side panels,
eyeball), but they come in different sizes and poses, so each is brought to
the same footing as the regular turret:

  scale       multiply the model by this (the defective one is built smaller)
  open        slide the side panels out by this much first (model units, after
              scaling): the stored mesh has them open
  wing_close  how far the panels slide in when closed
  gain        brighten the shell colours (textures are darker than in-game)
"""
import numpy as np

PROFILES = {
    # "Portal Turret" by Igrium: panels open in its rest pose
    'turret': dict(scale=1.0, open=0.0, wing_close=0.17, gain=1.35),
    # "Defective Turret - From Portal 2 (Original)" by David & 3D: built
    # smaller (scaled so its three feet stand where the regular turret's do;
    # it's a shorter turret), panels closed in its rest pose, a dark bare frame
    'defective': dict(scale=1.137, open=0.105, wing_close=0.105, gain=2.4),
}


def apply(profile, v, panel_of_vertex):
    """Scale the vertices and open the side panels (vertex groups 1 = left,
    2 = right); returns new vertices."""
    p = PROFILES[profile]
    v = v * p['scale']
    v[panel_of_vertex == 1, 0] -= p['open']
    v[panel_of_vertex == 2, 0] += p['open']
    return v
