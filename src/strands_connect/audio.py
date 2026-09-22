"""Small, original PCM earcon; no external audio assets or model call required."""

import array
import math
import sys


def tool_earcon(sample_rate: int = 24000) -> bytes:
    """A quiet 340 ms 'doop doop', with tapered edges and a short downward pitch sweep."""
    samples = array.array("h")
    for frequency in (440, 350):
        length = int(sample_rate * 0.13)
        for i in range(length):
            t = i / sample_rate
            envelope = math.sin(math.pi * i / length) ** 2
            phase = 2 * math.pi * (frequency * t - 65 * t * t)
            value = (math.sin(phase) + 0.12 * math.sin(2 * phase)) * envelope * 2100
            samples.append(round(value))
        samples.extend([0] * int(sample_rate * 0.04))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def chunks(pcm: bytes, sample_rate: int, milliseconds: int = 20):
    size = sample_rate * 2 * milliseconds // 1000
    for offset in range(0, len(pcm), size):
        yield pcm[offset : offset + size]
