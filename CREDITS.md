# Credits

Portal Turret is a fan-made watchface. It is not affiliated with or endorsed
by Valve Corporation. Portal, the turret and Aperture Science are trademarks
of Valve Corporation.

## Code

Everything in `src/`, `tools/`, `wscript`, `package.json` and `lite/package.json` is MIT licensed
(see `LICENSE`), by CATEIN.

`tools/ima_adpcm.py` comes from the author's own Pebble project
*pebble-still-alive* (same license).

## Turret model (CC BY 4.0)

The turret is based on **"Portal Turret"** by **Igrium**
(https://sketchfab.com/Sam54123), from
https://sketchfab.com/3d-models/portal-turret-6716037b4f174677a9aeb85405716e4e,
licensed under Creative Commons Attribution 4.0 International
(https://creativecommons.org/licenses/by/4.0/).

Changes made: the model was posed, stripped of hidden faces, simplified to
about 2000 triangles, given flat per-face colours taken from its textures and
packed into a compact binary format; its side panels are animated by the
watchface. These files are adaptations of the model and are shared under the
same CC BY 4.0 license:

- `resources/turret.bin` (made by `tools/convert_model.py`)
- the turret picture in `src/pkjs/turret_view.js` (made by `tools/render_view.py`)
- the close-up pictures (`resources/closeup~emery.bin`, `closeup~gabbro.bin`, made by `tools/render_closeup.py`)
- the turret icon (`resources/images/menu_icon.png`, `store/icon-*.png`, made by `tools/make_icon.py`)
- the turret in the screenshots, GIFs and banners in `store/`

The original model download (`portal_turret.zip`) is not included in this
repository; get it from the Sketchfab page above.

## Defective turret model (CC BY-NC 4.0)

Portal Turret Lite (built from `lite/`) doesn't include it.

The defective turret is based on **"Defective Turret - From Portal 2
(Original)"** by **David & 3D** (https://sketchfab.com/DavidAnd3D), from
https://sketchfab.com/3d-models/defective-turret-from-portal-2-original-4eca0877381f4208a94c7f43a08ffbdc,
licensed under Creative Commons Attribution-NonCommercial 4.0 International
(https://creativecommons.org/licenses/by-nc/4.0/). No commercial use.

Changes made: as for the regular turret (posed, hidden faces removed,
simplified, flat face colours from its textures, packed for the watch),
and also scaled so its three feet stand where the regular turret's do, its side panels posed
open, and its colours brightened (`tools/models.py`). These adaptations are
shared under the same CC BY-NC 4.0 license:

- `resources/turret_defective.bin` (made by `tools/convert_model.py --profile defective`)
- `resources/closeup_defective~emery.bin`, `closeup_defective~gabbro.bin` (made by
  `tools/render_closeup.py --profile defective`)

Its download (`defective_turret_-_from_portal_2_original.zip`) is not included
either.

## Voice lines and sounds (Valve)

`resources/voices.bin` holds turret voice lines ("Who's there?", "Are you
still there?", ...) and the turret's deploy, retract, firing and shutdown
sounds from Portal and Portal 2, and the defective turret's lines and
dry-fire clicks from Portal 2. `resources/voices_lite.bin` (Portal Turret
Lite) holds only the regular turret's. All (c) Valve Corporation, taken from the Portal Wiki
(https://theportalwiki.com/wiki/Turret_voice_lines and
https://theportalwiki.com/wiki/Defective_Turret_voice_lines) and re-encoded by
`tools/convert_audio.py`. They are **not** covered by this repository's MIT
license, are included for non-commercial fan use only, and belong to Valve.

## Everything else

The explosion and fire sounds in `resources/voices.bin` are synthesized by
`tools/make_explosion.py` and `tools/make_fire.py` (part of this project, MIT).

The test chamber, the eye and the laser are drawn by the watchface's own code.
The banners use Liberation Sans (SIL Open Font License).
