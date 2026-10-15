#!/usr/bin/env python3
"""Synthesize the explosion sound (a defective turret blowing up): an
original sound, so it's covered by the repository's MIT license.

usage: make_explosion.py out.wav   (needs numpy)

A sharp crack, a low falling thump, a rumbling noise body and some crackle.
"""
import sys
import wave

import numpy as np

RATE = 16000


def main():
    rng = np.random.default_rng(7)
    n = int(RATE * 1.5)
    t = np.arange(n) / RATE

    crack = rng.normal(0, 1, n) * np.exp(-t / 0.012)

    # brown-ish noise: integrated white noise, with the DC drift removed
    brown = np.cumsum(rng.normal(0, 1, n))
    brown -= np.convolve(brown, np.ones(801) / 801, mode='same')
    brown /= np.abs(brown).max()
    body = brown * np.minimum(t / 0.006, 1) * np.exp(-t / 0.38)

    freq = 70 * np.exp(-t / 0.4) + 32                  # falling low thump
    thump = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t / 0.22)

    crackle = np.zeros(n)
    for _ in range(90):
        at = rng.uniform(0.05, 1.0)
        i = int(at * RATE)
        k = rng.integers(20, 120)
        crackle[i:i + k] += rng.normal(0, 1, min(k, n - i)) * np.exp(-at / 0.35)

    s = 0.9 * crack + 1.0 * body + 0.8 * thump + 0.25 * crackle
    s = np.tanh(s * 1.6)                               # a little grit
    s *= 0.95 / np.abs(s).max()
    with wave.open(sys.argv[1], 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((s * 32767).astype(np.int16).tobytes())


if __name__ == '__main__':
    main()
