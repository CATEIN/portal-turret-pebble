# Portal Turret

A Pebble watchface for the **Pebble Time 2** (emery) and **Pebble Round 2** (gabbro): the turret from Portal, with its eye as the clock.

<p>
  <img src="store/screenshots/emery-flick.gif" alt="A wrist flick on the Pebble Time 2" width="200">
  <img src="store/screenshots/gabbro-flick.gif" alt="A wrist flick on the Pebble Round 2" width="260">
</p>

- **The eye is the clock.** The default view is a close-up of the turret's eye, a ring of 24 red wedges like the real turret's lens.
  - The wedge at the current minute glows along its whole length (the long hand).
  - The wedge at the current hour glows on its inner half (the short hand).
  - The time is also printed small on the eye's grey rim (can be turned off).
- **Flick your wrist** and the view zooms out to the whole turret, standing in a test chamber:
  - the side panels kick open and rock it onto one foot and back until it settles,
  - then it scans the room, panels sweeping left/right and up/down, with its laser sight following them,
  - after about 7 seconds it faces forward, folds its panels away and zooms back in to the eye. Flicking again while it's out keeps it out longer.
- **It talks** (Time 2 only, through its speaker): a random line when it deploys ("Who's there?", "Target acquired", ...) and when it goes back to sleep ("Are you still there?", "Hibernating", ...), plus the real deploy and retract sounds. Nothing plays when the watch is muted.

## Settings

In the Pebble app on your phone, open the watchface's settings:

- **Show the time under the eye** (on by default).
- **Volume** for the voice lines and sounds (Time 2 only). 0% turns them off.
- **Test chamber**: the turret's room, drawn from the watch's angle and showing every tile either watch can show.
  - Tap a wall panel or floor tile to switch it between white and black.
  - Hold a tile to split it into 4 small tiles, which can then be tapped one by one. Hold the middle of a split tile, where its 4 small tiles meet, to join them back.
  - "All white", "All black" and "Default" set the whole room.

The watch keeps the settings, so they survive restarts.

## How it works

The watch draws the turret itself: a low-poly copy of a 3D model (about 2000 triangles, `resources/turret.bin`) projected with a fixed-point camera (the watches have no FPU) and drawn with a painter's-algorithm scanline rasterizer and 4x4 ordered dithering, since the display has only 64 colours. The eye, the room and the laser go through the same camera so everything stays in place while it zooms and sways. The mesh is only loaded into RAM while the turret is on screen.

The voice lines are IMA ADPCM, decoded and mixed on the watch and streamed to the speaker. While a sound plays, the face leaves the CPU idle between frames, since the speaker is fed in the background.

## Building

You need the Pebble SDK (`pebble` tool, SDK 4.x).

    pebble build
    pebble install --emulator emery        # or --phone <your phone's IP>

### Regenerating the assets

The generated files are committed, so this is only needed to change them. The Python tools need numpy and Pillow (plus `fast-simplification` and `pygltflib` for the model, ffmpeg for the audio):

    python3 -m venv venv && venv/bin/pip install numpy pillow fast-simplification pygltflib

- **Model** (`resources/turret.bin`): download "Portal Turret" from [Sketchfab](https://sketchfab.com/3d-models/portal-turret-6716037b4f174677a9aeb85405716e4e) (glTF), then

      unzip portal_turret.zip -d model
      venv/bin/python tools/convert_model.py model/scene.gltf resources/turret.bin 2000

  It poses the rig, removes faces you can't see from outside, simplifies each part, takes face colours from the textures, fixes face winding and finds the eye.
- **Settings page turret** (`src/pkjs/turret_view.js`): `venv/bin/python tools/render_view.py resources/turret.bin src/pkjs/turret_view.js`
- **Voice lines** (`resources/voices.bin`, `src/c/voices.h`): save the clips from the [Portal Wiki](https://theportalwiki.com/wiki/Turret_voice_lines) into a folder (file names in `tools/convert_audio.py`), then `python3 tools/convert_audio.py path/to/wavs resources/voices.bin src/c/voices.h`
- **Store screenshots and GIFs** (`store/screenshots/`): `venv/bin/python tools/capture_store.py` (uses the emulator; takes a while)
- **Store banners** (`store/banner-*.png`): `venv/bin/python tools/make_store_assets.py`
- **Icon** (`resources/images/menu_icon.png` for the watch's menu, `store/icon-*.png`): `venv/bin/python tools/make_icon.py`

## Layout

    src/c/main.c          the watchface: camera, rasterizer, eye, room, laser, animation, settings
    src/c/audio.c         voice line playback (Time 2)
    src/pkjs/             phone side: the settings page and sending settings to the watch
    resources/            turret.bin (the model), voices.bin (the sounds), the menu icon
    tools/                asset converters and store asset tools
    store/                appstore listing, screenshots, GIFs and banners

## Credits and license

The code is MIT licensed (see [LICENSE](LICENSE)). The turret model is
"[Portal Turret](https://sketchfab.com/3d-models/portal-turret-6716037b4f174677a9aeb85405716e4e)"
by [Igrium](https://sketchfab.com/Sam54123), CC BY 4.0, and the files made from it
are shared under the same license. The voice lines and sounds are (c) Valve
Corporation and not covered by the MIT license. This is a fan project, not
affiliated with Valve. Details in [CREDITS.md](CREDITS.md).
