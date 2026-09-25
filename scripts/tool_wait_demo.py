"""Offline developer rehearsal; run from a checkout with python -m scripts.tool_wait_demo.

Uses the real adapter/Strands loop and the repository's simulated AWS/provider fixtures.
No AWS credentials or provider API keys are read. This is not a live Connect recording.
"""

import argparse
import asyncio
import base64
import json
import time
import wave
from pathlib import Path

from examples.shared.retail import configure_session, validate_tool_delay
from tests.fakes import (
    CONTACT,
    INSTANCE,
    ContactClient,
    MemorySocket,
    WaitingModel,
    audio_input,
    audio_source,
    frame,
    init_frame,
)


def write_preview(cue_frames, evidence, output):
    """Replay one uninterrupted cue span on its sample clock, never its arrival clock.

    This capture has no speech/interruption inside the cue span. Network jitter and
    receiver buffering are not simulated; arrival timestamps remain diagnostics.
    """
    if not cue_frames:
        raise ValueError("No cue audio was captured")
    output.mkdir(parents=True, exist_ok=True)
    rate = evidence["sample_rate"]
    timestamps = [timestamp for timestamp, _ in cue_frames]
    stream = b"".join(pcm for _, pcm in cue_frames)
    lead_samples = round(timestamps[0] * rate)
    # Chunk arrival offsets must NEVER insert silence or overwrite adjacent PCM.
    pcm = b"\0\0" * lead_samples + stream + b"\0\0" * round(0.6 * rate)
    with wave.open(str(output / "soft-pulse-tool-wait.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    evidence = {
        **evidence,
        "preview_playback": "Consecutive PCM samples; arrival timestamps are diagnostic only",
        "preview_lead_samples": lead_samples,
        "preview_cue_end_seconds": (lead_samples + len(stream) // 2) / rate,
        "cue_frame_times": timestamps,
    }
    (output / "timing.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (output / "cue-stream.pcm").write_bytes(stream)
    html = Path(__file__).with_suffix(".html").read_text()
    replacements = {
        "__AUDIO__": base64.b64encode((output / "soft-pulse-tool-wait.wav").read_bytes()).decode(),
        "__DATA__": json.dumps(evidence),
        "__DELAY__": str(evidence["delay_seconds"]),
        "__FRAMES__": str(evidence["cue_frames_before_result"]),
        "__INPUT__": str(evidence["caller_audio_delivered_seconds"]),
        "__RESULT__": str(evidence["tool_result_seconds"]),
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    (output / "index.html").write_text(html)
    return evidence


async def capture(delay):
    started = time.monotonic()
    captured = []

    class Socket(MemorySocket):
        async def send(self, payload):
            await super().send(payload)
            message = self.frames[-1]
            if audio_source(message) == "tool_cue":
                raw = message["result"]["artifactUpdate"]["artifact"]["parts"][0]["raw"]
                captured.append((time.monotonic() - started, base64.b64decode(raw)))

    socket, client = Socket(), ContactClient()
    model = WaitingModel(client, 16000)
    session = configure_session(
        socket,
        connect_client=client,
        model_factory=lambda: model,
        instance_arn=INSTANCE,
        provider="offline-rehearsal",
        demo_tool_delay_seconds=delay,
    )
    await socket.incoming.put(init_frame())
    await socket.incoming.put(frame("CHANNEL_STATE", {"channelState": {"state": "READY"}}))
    await socket.incoming.put(audio_input())
    task = asyncio.create_task(session.run())
    try:
        async with asyncio.timeout(delay + 5):
            while audio_source(await socket.outgoing.get()) != "tool_cue":
                pass
            tool_start = next(iter(session.pending_tools.values()))["started"]
            tool_start_offset = time.monotonic() - started - (time.time_ns() - tool_start) / 1e9
            await socket.incoming.put(audio_input())
            await model.input_during_wait.wait()
            input_at = time.monotonic() - started
            await model.result_received.wait()
            result_at = model.result_at - started
            while audio_source(await socket.outgoing.get()) != "model":
                pass
    finally:
        await socket.incoming.put(None)
        await asyncio.wait_for(task, 3)
    if session.failed or input_at >= result_at:
        raise RuntimeError("Rehearsal failed to demonstrate concurrent input and tool execution")
    return captured, {
        "mode": "Offline rehearsal: real Strands BidiAgent, simulated provider and AWS",
        "delay_seconds": delay,
        "tool_start_seconds": round(tool_start_offset, 3),
        "first_cue_seconds": round(captured[0][0], 3),
        "caller_audio_delivered_seconds": round(input_at, 3),
        "tool_result_seconds": round(result_at, 3),
        "cue_frames_before_result": sum(t < result_at for t, _ in captured),
        "contact_status": client.attributes[CONTACT]["OrderStatus"],
        "sample_rate": 24000,
        "cue_frame_seconds": 0.02,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", default=15, type=float, help="Lookup delay, 2–30 seconds (default 15)")
    parser.add_argument("--output", default=Path("build/tool-wait-demo"), type=Path)
    args = parser.parse_args()
    try:
        delay = validate_tool_delay(args.delay)
        if delay < 2:
            raise ValueError("The audible rehearsal needs a delay of at least two seconds")
    except ValueError as error:
        parser.error(str(error))
    frames, evidence = asyncio.run(capture(delay))
    write_preview(frames, evidence, args.output)
    print(json.dumps(evidence, indent=2))
    print("Open " + str((args.output / "index.html").resolve()))


if __name__ == "__main__":
    main()
