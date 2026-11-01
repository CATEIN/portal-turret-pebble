# Appstore listing

For the Repebble appstore: Portal Turret (`package.json`), and below it
Portal Turret Lite (`lite/package.json`), which leaves out the defective turret. Assets are in this folder; regenerate them with
`tools/capture_store.py` (screenshots and GIFs, from the emulator) and
`tools/make_store_assets.py` (banners).

- **Name:** Portal Turret
- **Type:** Watchface
- **Platforms:** Pebble Time / Time Steel (basalt), Pebble Time Round (chalk), Pebble Time 2 (emery), Pebble Round 2 (gabbro)
- **Icons** (optional for watchfaces): `icon-large.png` (144x144), `icon-small.png` (48x48)
- **Banner** (720x320, one per platform): `banner-dark.png` or `banner-light.png`
- **Screenshots** (unframed, at display size, max 5 per platform):
  - emery: `screenshots/emery-flick.gif`, `screenshots/emery-eye.png`, `screenshots/emery-turret.png`, `screenshots/emery-chamber.png`
  - gabbro: `screenshots/gabbro-flick.gif`, `screenshots/gabbro-eye.png`, `screenshots/gabbro-turret.png`, `screenshots/gabbro-chamber.png`
  - basalt: `screenshots/basalt-flick.gif`, `screenshots/basalt-eye.png`, `screenshots/basalt-turret.png`, `screenshots/basalt-chamber.png`
  - chalk: `screenshots/chalk-flick.gif`, `screenshots/chalk-eye.png`, `screenshots/chalk-turret.png`, `screenshots/chalk-chamber.png`
- **Release:** `build/portal-turret.pbw` (version from package.json)
- **Source code:** https://github.com/CATEIN/portal-turret-pebble
- **Website:** _(optional)_

## Description

The turret from Portal, on your wrist. Its eye is the clock.

We’ve stuck one of those adorable little murder machines on your arm. Its big red eye is the clock. Twenty-four angry wedges, just like the real lens. Minute wedge lights up the whole way. Hour wedge glows on the inner half. Tiny numbers on the rim if you still need the training wheels.
Flick your wrist and it zooms out. Full turret. Real 3D model standing in a test chamber. Side panels kick open. Scans the room with the laser. Then folds back up and goes right back to watching you.
Flick again while it’s out and you knock it over. It falls, still firing wildly, shuts down, and a claw hauls it away and lowers a fresh one. Sometimes it spots you first. Locks on. Opens fire. Only knocking it over saves you. Some of them are defective: no bullets, plenty of excuses, and a nasty habit of catching fire and exploding. Science!
On the Pebble Time 2 it talks. Seventy-eight real lines from the game. “Who’s there?” “Are you still there?” “Gotcha!” “I don’t blame you.” And more. Real turret sounds included.
Settings — because even science needs a few knobs:

Time numbers under the eye: on or off. Some of you still need them. Fine.
24-hour dial. One wedge per hour, once around a day. For people who think twelve hours is a cop-out.
Volume (Time 2 only). Crank it or set it to zero and make the little thing shut its mouth.
Chance it sees you. Turn it up if you like living dangerously.
Chance of a defective turret, and of it catching fire or exploding. You’re welcome.
Design the test chamber yourself. Tap tiles to paint them black or white. Hold one to split it into four. Make it as sterile and judgmental as you want.

The tech boys say we have to put these credits here so we don’t get sued:

“Portal Turret” model by Igrium, CC BY 4.0; “Defective Turret” model by David & 3D, CC BY-NC 4.0 (both on Sketchfab). Voice lines and sounds © Valve Corporation. Fan project, not affiliated with Valve. Source (MIT): github.com/CATEIN/portal-turret-pebble

## Release notes (1.2.0)

CHANGELOG. PAY ATTENTION. AGAIN.
More wrists!

The turret now runs on the Pebble Time, Time Steel and Time Round. Those only give an app half the memory, so the boys in the lab built a lighter turret. Same eye. Same attitude.
New setting:

24-hour dial. One wedge per hour, once around a day, midnight at the top. Twelve hours is for quitters.

Bigger floor tiles. Same size as the wall panels now. Your old test chamber carries over: each big tile is built from the four little ones it covers. We don't throw out good science.
The test chamber on your phone zooms out to show every tile the watch can see. No more painting blind.
Still a big app. Install might say it failed. Wait a minute. It usually works.

## Release notes (1.1.0)

CHANGELOG. PAY ATTENTION.
Knock it over!

Flick your wrist again while it’s out and the turret topples, still firing. Shuts down. Claw drops in a replacement. Test continues.
New settings:

Chance it sees you. Locks on. Opens fire. Knock it over or die.
Defective turret. Might catch fire. Might explode. Science!

78 voice lines on the Time 2. Camera and rocking now go either way. Sharper eye close-up. Smoother sound.
Big app. Install might say it failed. Wait a minute. It usually works.
Portal Turret Lite (no defective turret) is on GitHub.

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

## Release notes (1.2.0)

Now also on the Pebble Time, Time Steel and Time Round. New setting: a 24-hour dial, a wedge per hour. Bigger floor tiles, and the whole room in the phone's test chamber.

## Release notes (1.1.0)

First release of Portal Turret Lite: Portal Turret without the defective turret (39 voice lines instead of 78), so it's about half the size and installs faster.
