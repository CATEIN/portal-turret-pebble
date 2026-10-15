# Appstore listing

For the Repebble appstore: Portal Turret (`package.json`), and below it
Portal Turret Lite (`lite/package.json`), which leaves out the defective turret. Assets are in this folder; regenerate them with
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

The face is a close-up of the turret's eye: 24 red wedges like the real lens. The wedge at the current minute glows along its whole length, the one at the hour on its inner half, and the time is printed small on the eye's rim.

Flick your wrist and it zooms out to the whole turret, a real 3D model standing in a test chamber. Its side panels kick open and it scans the room with its laser sight, then folds up and goes back to watching you.

Flick again while it's out to knock it over: it falls firing wildly, shuts down, and a claw carries it away and lowers a new one. Sometimes it spots you: it locks on and opens fire, and only knocking it over saves you. Some turrets are defective: no bullets, lots of excuses, and a habit of catching fire and exploding.

On the Pebble Time 2 it talks, with 78 lines from the game: "Who's there?", "Are you still there?", "Gotcha!", "I don't blame you" and more, with the real turret sounds.

Settings (in the Pebble app):
- Show or hide the time under the eye
- Volume (Time 2 only; 0% turns the sounds off)
- Chance of the turret seeing you
- Chance of a defective turret, and of it catching fire or exploding
- Design the test chamber: tap tiles to make them white or black, hold one to split it into 4

Credits: "Portal Turret" model by Igrium, CC BY 4.0; "Defective Turret" model by David & 3D, CC BY-NC 4.0 (both on Sketchfab). Turret voice lines and sounds (c) Valve Corporation. Fan project, not affiliated with Valve. Source code (MIT): github.com/CATEIN/portal-turret-pebble

## Release notes (1.1.0)

Knock it over! Flick your wrist again while the turret is zoomed out and it falls over firing, shuts down and a claw brings in a replacement. New settings: the chance of the turret seeing you (it locks on and opens fire; knock it over to survive), and the defective turret from Portal 2, which might catch fire and explode. 78 voice lines on the Pebble Time 2. The camera and the turret's rocking now go either way. A detailed close-up of the eye, and smoother sound. This is a big app: the install may say it failed, but wait a minute longer, it usually installs anyway. Portal Turret Lite is the smaller version without the defective turret.

## Release notes (1.0.0)

First release.

---

# Portal Turret Lite

The same listing, without the defective turret: name **Portal Turret Lite**,
release `lite/build/lite.pbw`, same screenshots, banners and icons.

## Description

As above, with these changes: leave out the sentence about defective turrets
and the defective turret settings line, say "39 lines" instead of "78 lines",
credit only the "Portal Turret" model, and add at the end: "A smaller version
of Portal Turret, without the defective turret; it installs faster."

## Release notes (1.1.0)

First release of Portal Turret Lite: Portal Turret without the defective turret (39 voice lines instead of 78), so it's about half the size and installs faster.
