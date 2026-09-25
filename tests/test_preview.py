"""Regression: transport timing must not punch gaps into the preview waveform."""

import base64
import json
import re
import wave

from scripts.tool_wait_demo import write_preview
from strands_connect.audio import chunks, soft_pulse


def test_jittered_frames_preserve_every_sample_and_keep_timing_separate(tmp_path):
    frames = list(chunks(soft_pulse(24000), 24000))[:4]
    # These arrival intervals would both insert gaps and overwrite audio if used
    # as sample positions. The WAV must instead preserve every frame byte-for-byte.
    arrivals = [0.1, 0.123, 0.139, 0.167]
    evidence = {
        "sample_rate": 24000,
        "delay_seconds": 2,
        "cue_frames_before_result": 4,
        "caller_audio_delivered_seconds": 0.13,
        "tool_result_seconds": 2,
    }
    write_preview(list(zip(arrivals, frames)), evidence, tmp_path)
    with wave.open(str(tmp_path / "soft-pulse-tool-wait.wav"), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
        actual = wav.readframes(wav.getnframes())
    assert actual == b"\0\0" * 2400 + b"".join(frames) + b"\0\0" * 14400
    timing = json.loads((tmp_path / "timing.json").read_text())
    assert timing["cue_frame_times"] == arrivals
    assert timing["preview_cue_end_seconds"] == 0.18
    html = (tmp_path / "index.html").read_text()
    embedded = base64.b64decode(re.search(r"data:audio/wav;base64,([^\"]+)", html).group(1))
    assert embedded == (tmp_path / "soft-pulse-tool-wait.wav").read_bytes()
    assert "__AUDIO__" not in html and "__DATA__" not in html
