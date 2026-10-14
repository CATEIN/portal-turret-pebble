# Appstore listing

For the Repebble appstore. Assets are in this folder; regenerate them with
`tools/capture_store.py` (screenshots and GIFs, from the emulator) and
`tools/make_store_assets.py` (banners).

- **Name:** Portal Turret
- **Type:** Watchface
- **Platforms:** Pebble Time 2 (emery), Pebble Round 2 (gabbro)
- **Icons** (optional for watchfaces): `icon-large.png` (144x144), `icon-small.png` (48x48)
- **Banner** (720x320, one per platform): `banner-dark.png` or `banner-light.png`
- **Screenshots** (unframed, at display size, max 5 per platform):
  - emery: `screenshots/emery-flick.gif`, `screenshots/emery-eye.png`, `screenshots/emery-turret.png`, `screenshots/emery-chamber.png`
  - gabbro: `screenshots/gabbro-flick.gif`, `screenshots/gabbro-eye.png`, `screenshots/gabbro-turret.png`, `screenshots/gabbro-chamber.png`
- **Release:** `build/portal-turret.pbw` (version from package.json)
- **Source code:** https://github.com/CATEIN/portal-turret-pebble
- **Website:** _(optional)_

## Description (max 1600 characters)

The turret from Portal, on your wrist. Its eye is the clock.

The face is a close-up of the turret's eye: 24 red wedges like the real lens. The wedge at the current minute glows along its whole length, the one at the hour glows on its inner half, and the time is printed small on the eye's rim.

Flick your wrist and it zooms out to the whole turret, standing in a test chamber. The side panels kick open, rocking it onto one foot until it settles, and it scans the room with its laser sight. A few seconds later it folds up and goes back to watching you.

On the Pebble Time 2 it talks: "Who's there?" when it deploys, "Are you still there?" when it goes back to sleep, and more, with the real deploy and retract sounds. Nothing plays while the watch is muted.

The whole turret is a real 3D model rendered on the watch, with perspective, lighting and a camera that sways while it's out.

Settings (in the Pebble app):
- Show or hide the time under the eye
- Volume (Time 2 only; 0% turns the sounds off)
- Design the test chamber: tap wall panels and floor tiles to make them white or black, hold one to split it into 4 small tiles

Credits: turret model "Portal Turret" by Igrium (sketchfab.com/Sam54123), CC BY 4.0. Turret voice lines and sounds (c) Valve Corporation. Fan project, not affiliated with Valve. Source code (MIT): github.com/CATEIN/portal-turret-pebble

## Release notes (1.0.0)

First release.
