#!/usr/bin/env python3
"""Capture the appstore screenshots and flick GIFs from the emulator.

usage: python3 tools/capture_store.py [emery] [gabbro]   (needs Pillow and the Pebble SDK)

For each platform it builds special versions of the face (main.c with a few
#defines put in front, restored afterwards), installs them on the emulator
and saves, unframed, at the display's own size:

  store/screenshots/<platform>-flick.gif     a whole flick, frame by frame
  store/screenshots/<platform>-eye.png       the close-up (the default view)
  store/screenshots/<platform>-turret.png    zoomed out, scanning
  store/screenshots/<platform>-chamber.png   zoomed out, in a custom room

The GIF comes from STORE_CAPTURE (see main.c): the face flicks by itself and
steps the animation 80 ms at a time, holding each frame for 3 s, longer than a
screenshot takes, while this script screenshots it over and over and keeps
each new picture. That way every frame is captured at its proper timing,
however slow the emulator is. (Every frame differs from the one before, since
the view sways the whole time the turret is zoomed out.)
The clock shows 10:08 in all of them (STORE_TIME).
"""
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "src" / "c" / "main.c"
SHOTS = ROOT / "store" / "screenshots"
FRAME_MS = 80          # CAPTURE_DT_MS in main.c
FIRST_MS = 1500        # how long the GIF lingers on the close-up first
LAST_MS = 1200         # ... and at the end

# zoom, panels, sway, scan, rocking (ms since the panels opened; past the end = still)
TURRET_POSE = dict(DEBUG_ZOOM=1000, DEBUG_WING=1000, DEBUG_SWAY=1750, DEBUG_SCAN=700, DEBUG_TIP=2400)
CHAMBER_POSE = dict(DEBUG_ZOOM=1000, DEBUG_WING=1000, DEBUG_SWAY=5200, DEBUG_SCAN=2300, DEBUG_TIP=2400)


def run(*cmd, timeout=600):
    return subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True, timeout=timeout)


def install(platform, defines):
    """Build with these #defines at the top of main.c, install on the emulator."""
    original = MAIN.read_text()
    head = "".join(f"#define {k} {v}\n" for k, v in defines.items())
    try:
        MAIN.write_text(head + original)
        run("pebble", "build")
    finally:
        MAIN.write_text(original)
    run("pebble", "install", "--emulator", platform)


def screenshot(platform, path):
    run("pebble", "screenshot", "--emulator", platform, "--no-correction", "--no-open", str(path),
        timeout=120)


def still(platform, name, defines):
    install(platform, {"STORE_TIME": 1, **defines})
    time.sleep(4)
    path = SHOTS / f"{platform}-{name}.png"
    screenshot(platform, path)
    print(f"  {path.relative_to(ROOT)}")


def flick_gif(platform):
    install(platform, {"STORE_CAPTURE": 1})
    tmp = SHOTS / f".{platform}-frame.png"
    frames = []
    try:
        deadline = time.time() + 1500
        while time.time() < deadline:
            screenshot(platform, tmp)
            img = Image.open(tmp).convert("RGB")
            if not frames or img.tobytes() != frames[-1].tobytes():
                frames.append(img)
                print(f"\r  frame {len(frames) - 1}", end="", flush=True)
            # done once it has zoomed all the way back to the first frame
            if len(frames) > 10 and img.tobytes() == frames[0].tobytes():
                break
        else:
            sys.exit(f"{platform}: the animation never finished")
    finally:
        tmp.unlink(missing_ok=True)
    print()

    durations = [FIRST_MS] + [FRAME_MS] * (len(frames) - 2) + [LAST_MS]
    path = SHOTS / f"{platform}-flick.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   optimize=False, disposal=1)
    print(f"  {path.relative_to(ROOT)} ({len(frames)} frames)")


def main():
    platforms = sys.argv[1:] or ["emery", "gabbro"]
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        for p in platforms:
            print(p)
            still(p, "eye", {"DEBUG_POSE": 1, "DEBUG_ZOOM": 0, "DEBUG_WING": 0, "DEBUG_SWAY": 0})
            still(p, "turret", {"DEBUG_POSE": 1, **TURRET_POSE})
            still(p, "chamber", {"DEBUG_POSE": 1, "STORE_ROOM": 1, **CHAMBER_POSE})
            flick_gif(p)
    finally:
        run("pebble", "build")  # leave a normal build behind


if __name__ == "__main__":
    main()
