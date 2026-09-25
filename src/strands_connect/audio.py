"""Original PCM tool-wait sounds; no external audio assets or model call required."""

import array
import math
import sys
from functools import lru_cache


@lru_cache(maxsize=3)
def soft_pulse(sample_rate: int = 24000) -> bytes:
    """Original breathing chord with two alternating electric-piano accents.

    A seamless 7.6-second mono PCM16 loop, peaking at -26.4 dBFS. Pad oscillators
    use whole cycles and circular reflections to avoid a click at the loop seam.
    Render once per negotiated rate, outside the audio event loop.
    """
    if sample_rate not in (8000, 16000, 24000):
        raise ValueError("Unsupported PCM sample rate")
    duration = 7.6
    size = round(sample_rate * duration)
    tau = 2 * math.pi
    frequencies = [round(f * duration) / duration for f in (293.665, 369.994, 440)]
    dry = []
    for i in range(size):
        t = i / sample_rate
        breathing = (0.5 - 0.5 * math.cos(tau * t / 3.8)) ** 2
        chord = (
            0.46 * math.sin(tau * frequencies[0] * t + 0.08 * math.sin(tau * t / duration))
            + 0.30 * math.sin(tau * frequencies[1] * t)
            + 0.22 * math.sin(tau * frequencies[2] * t)
        )
        value = 0.040 * (0.16 + 0.84 * breathing) * chord
        for start, frequency in ((0.9, 587.330), (4.7, 659.255)):
            age = t - start
            if 0 <= age < 1.8:
                envelope = (1 - math.exp(-age / 0.012)) * math.exp(-age / 0.58)
                envelope *= min(1, (1.8 - age) / 0.10)
                phase = tau * frequency * age
                note = math.sin(phase + 0.5 * math.exp(-age / 0.12) * math.sin(2 * phase))
                note += 0.10 * math.exp(-age / 0.25) * math.sin(3 * phase)
                note += 0.055 * math.sin(phase * 1.002)
                value += 0.017 * envelope * note
        dry.append(value)
    reflections = [
        (round(delay * sample_rate), gain) for delay, gain in ((0.081, 0.075), (0.163, 0.040), (0.277, 0.024))
    ]
    wet = [
        value + sum(gain * dry[(i - delay) % size] for delay, gain in reflections)
        for i, value in enumerate(dry)
    ]
    scale = 32767 * 0.048 / max(abs(value) for value in wet)
    samples = array.array("h", (round(value * scale) for value in wet))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def fade_in(pcm: bytes, sample_rate: int, offset: int, seconds: float = 0.7) -> bytes:
    """Apply only the initial fade; offset counts samples already played."""
    length = round(sample_rate * seconds)
    if offset >= length:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    for i in range(min(len(samples), length - offset)):
        samples[i] = round(samples[i] * (offset + i) / length)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


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
