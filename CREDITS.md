# Credits

Portal Turret is a fan-made watchface. It is not affiliated with or endorsed
by Valve Corporation. Portal, the turret and Aperture Science are trademarks
of Valve Corporation.

## Code

Everything in `src/`, `tools/`, `wscript` and `package.json` is MIT licensed
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
- the turret in the screenshots, GIFs and banners in `store/`

The original model download (`portal_turret.zip`) is not included in this
repository; get it from the Sketchfab page above.

## Voice lines and sounds (Valve)

`resources/voices.bin` holds turret voice lines ("Who's there?", "Are you
still there?", ...) and the turret's deploy and retract sounds from Portal and
Portal 2, (c) Valve Corporation, taken from the Portal Wiki
(https://theportalwiki.com/wiki/Turret_voice_lines) and re-encoded by
`tools/convert_audio.py`. They are **not** covered by this repository's MIT
license, are included for non-commercial fan use only, and belong to Valve.

## Everything else

The test chamber, the eye and the laser are drawn by the watchface's own code.
The banners use Liberation Sans (SIL Open Font License).
