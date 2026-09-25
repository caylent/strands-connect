import array
import sys

import pytest

from strands_connect.audio import chunks, fade_in, soft_pulse


@pytest.mark.parametrize("rate", [8000, 16000, 24000])
def test_soft_pulse_is_quiet_mono_pcm_with_a_smooth_loop_seam(rate):
    pcm = soft_pulse(rate)
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    assert len(samples) == round(7.6 * rate)
    assert 1500 <= max(abs(value) for value in samples) <= 1574
    assert abs(sum(samples) / len(samples)) < 5
    assert abs(samples[0] - samples[-1]) < 120
    assert b"".join(chunks(pcm, rate)) == pcm
    assert soft_pulse(rate) is pcm  # Subsequent contacts reuse the rendered loop.
    first = array.array("h")
    first.frombytes(fade_in(pcm[: rate * 2 // 50], rate, 0))
    assert first[0] == 0
    assert fade_in(pcm, rate, rate) is pcm
