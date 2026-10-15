#!/usr/bin/env python3
"""Synthesize the burning sound (a defective turret on fire): a soft roar
with crackles and pops, about a second, to be played over and over. An
original sound, so it's covered by the repository's MIT license.

usage: make_fire.py out.wav   (needs numpy)
"""
import sys
import wave

import numpy as np

RATE = 16000


def main():
    rng = np.random.default_rng(11)
    n = int(RATE * 1.0)
    t = np.arange(n) / RATE
    # roar: low-passed noise, gently swelling
    roar = rng.normal(0, 1, n)
    for _ in range(3):
        roar = np.convolve(roar, np.ones(9) / 9, mode='same')
    roar /= np.abs(roar).max()
    roar *= 0.55 + 0.25 * np.sin(2 * np.pi * 2.3 * t) ** 2
    # crackles: short bright bursts at random
    crackle = np.zeros(n)
    for _ in range(70):
        i = rng.integers(0, n - 200)
        k = rng.integers(8, 60)
        crackle[i:i + k] += rng.normal(0, 1, k) * rng.uniform(0.3, 1.0) * np.exp(-np.arange(k) / (k / 3))
    s = roar + 0.6 * crackle
    fade = np.minimum(1, np.minimum(t / 0.03, (1.0 - t) / 0.03))  # no clicks when it repeats
    s *= fade
    s *= 0.9 / np.abs(s).max()
    with wave.open(sys.argv[1], 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((s * 32767).astype(np.int16).tobytes())


if __name__ == '__main__':
    main()
