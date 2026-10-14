"""
ima_adpcm.py

A standard IMA ADPCM 4-bit codec (mono, 16-bit PCM in/out), implemented
from the classic public-domain step/index tables. This is a widely used,
well-documented algorithm (the same one behind e.g. Microsoft's and
WAV's IMA ADPCM) -- nothing proprietary or copyrighted here, just table
lookups and a differential predictor.

4 bits/sample, so at a given sample rate this is exactly half the size
of 8-bit PCM at the same rate, or a quarter of 16-bit PCM.

The encoder and decoder MUST stay in lockstep (the encoder simulates the
same predictor update the decoder will perform), so this module doubles
as the reference the C decoder in src/c/audio.c is checked against.
"""

STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
    157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
    724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024,
    3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899,
    15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
]

INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]


def _clamp(val, lo, hi):
    return lo if val < lo else hi if val > hi else val


def encode(samples):
    """samples: iterable of signed 16-bit ints. Returns packed bytes,
    2 samples per byte (low nibble = first sample, high nibble = second).
    Starts from predictor=0, step_index=0 (silence), matching the decoder's
    starting state -- no block header is written."""
    predictor = 0
    step_index = 0
    nibbles = []

    for sample in samples:
        sample = _clamp(sample, -32768, 32767)
        diff = sample - predictor
        sign = 8 if diff < 0 else 0
        if diff < 0:
            diff = -diff

        step = STEP_TABLE[step_index]
        delta = 0
        tmp_step = step

        if diff >= tmp_step:
            delta |= 4
            diff -= tmp_step
        tmp_step >>= 1
        if diff >= tmp_step:
            delta |= 2
            diff -= tmp_step
        tmp_step >>= 1
        if diff >= tmp_step:
            delta |= 1

        nibble = sign | delta

        # Predictor update -- must exactly match what the decoder does.
        diffq = step >> 3
        if delta & 4:
            diffq += step
        if delta & 2:
            diffq += step >> 1
        if delta & 1:
            diffq += step >> 2
        if sign:
            predictor -= diffq
        else:
            predictor += diffq
        predictor = _clamp(predictor, -32768, 32767)

        step_index += INDEX_TABLE[nibble]
        step_index = _clamp(step_index, 0, len(STEP_TABLE) - 1)

        nibbles.append(nibble)

    out = bytearray()
    for i in range(0, len(nibbles), 2):
        lo = nibbles[i]
        hi = nibbles[i + 1] if i + 1 < len(nibbles) else 0
        out.append((hi << 4) | lo)
    return bytes(out)


def decode(data, num_samples=None):
    """Reference decoder, used only to self-test the encoder above (the
    real decode happens on-watch in C -- see src/c/audio.c). Returns a list of
    signed 16-bit ints."""
    predictor = 0
    step_index = 0
    out = []

    def decode_nibble(nibble):
        nonlocal predictor, step_index
        step = STEP_TABLE[step_index]
        diffq = step >> 3
        if nibble & 4:
            diffq += step
        if nibble & 2:
            diffq += step >> 1
        if nibble & 1:
            diffq += step >> 2
        if nibble & 8:
            predictor -= diffq
        else:
            predictor += diffq
        predictor_clamped = _clamp(predictor, -32768, 32767)
        predictor = predictor_clamped
        step_index += INDEX_TABLE[nibble]
        step_index = _clamp(step_index, 0, len(STEP_TABLE) - 1)
        return predictor

    for byte in data:
        lo = byte & 0x0F
        hi = (byte >> 4) & 0x0F
        out.append(decode_nibble(lo))
        if num_samples is None or len(out) < num_samples:
            out.append(decode_nibble(hi))

    if num_samples is not None:
        out = out[:num_samples]
    return out
