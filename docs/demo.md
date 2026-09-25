# Demonstrating a slow tool with live audio

All three provider apps use the same synthetic retail tool. Ask **“Where is order 1042?”**. The assistant is prompted to briefly acknowledge the request, then look it up. The lookup intentionally waits eight seconds without blocking the voice stream. The soft pulse plays during the wait, and the hook saves `OrderId=1042` / `OrderStatus=Shipped` before releasing the result to the model. The model can then explain the result.

The sound comes from locally generated PCM, not the voice provider. Tool execution and both audio directions run concurrently. The pulse yields to model speech; this is not a mix of waiting music over spoken responses. Model wording and acknowledgement timing still vary by provider.

## Controls

Set these before starting any provider app:

```sh
export DEMO_TOOL_DELAY_SECONDS=15  # Default 8; 15 makes repetition easy to hear.
export TOOL_CUE_ENABLED=true      # Default true; false gives a silent-wait comparison.
uv run python -m examples.connect_gemini.app
```

Use the OpenAI or Nova 2 Sonic entrypoint to run the same demonstration there. `DEMO_TOOL_DELAY_SECONDS=0` removes the artificial delay. Only finite numbers between 0 and 30 are accepted; invalid settings fail at app startup. Every lookup, including an unknown order, uses the configured delay. Contact reads, writes, completion, and escalation do not acquire an artificial delay.

For AgentCore, set the template parameter `DemoToolDelaySeconds` when deploying. It defaults to eight seconds. Restart local apps or update the hosted runtime to apply a changed setting. The setting belongs to the example application, not `ConnectSession` or the model's tool schema. Real applications should await their own business APIs without a demo delay.

## What to show

1. **Normal lookup:** ask for 1042. After the initial acknowledgement, hear the pulse while `lookup_order` remains pending. It starts no earlier than 700 ms into the tool call and fades in. With a 15-second delay, listen through a loop boundary.
2. **Speech during the wait:** the stream remains open. Caller PCM still reaches the provider, which decides whether to interrupt or answer. A detected interruption stops the cue. Ordinary barge-in does not cancel an already running Strands business tool; disconnecting the session cancels this asynchronous demo lookup.
3. **Unknown order:** ask for 9999. The result says only the synthetic order 1042 is available; it must not fabricate an order status. Existing saved attributes still describe the last successful lookup, not the unknown order.
4. **Disconnect during the wait:** hang up before the result. The synthetic lookup is cancelled and cannot subsequently write an order result. This does not imply cancellation or rollback of an AWS operation already running in a thread.
5. **Completion / escalation:** after a result, say goodbye or ask for a human. Check disposition, notes, and flow handback. A human queue must exist in your Connect flow for an actual transfer.
6. **Persistence failure:** in a dedicated test environment, deny a contact write. The model must receive an error instead of a verified success. Do not automatically repeat a business action to recover a failed save. The current fail-closed lifecycle can require disconnect or the session deadline; this example does not promise recovery or successful handoff after a persistence failure.

The pulse pauses through the estimated duration of queued model PCM plus a short silence margin, then fades back in if work is still pending. Connect supplies no acknowledged playback position, so this is a local estimate, not proof of what a caller has heard. A caller interruption cancels the cue for that pending call; it does not automatically restart.

## Evidence and offline rehearsal

Generate an audio player and measured tool/input/output timeline from a repository checkout:

```sh
uv sync --all-extras --group dev
uv run python -m scripts.tool_wait_demo
# Open build/tool-wait-demo/index.html in your browser.
```

The rehearsal defaults to 15 seconds. Use `--delay 8` for a shorter wait and
`--output build/my-rehearsal` to choose another output directory. The audible rehearsal
accepts 2–30 seconds so there is time to hear the cue; the provider apps still accept
0–30 seconds. The script uses the repository's test fixtures and is intentionally a
checkout-only developer tool, not part of the installed library API.

The generated WAV preserves captured PCM samples consecutively. Arrival timestamps
are recorded separately in `timing.json`; they must not become gaps or overwritten
samples in the audio. The HTML embeds the WAV so it can be opened without a server.
This rehearsal contains one uninterrupted cue span and does not model receiver jitter
buffering, speech interruptions, or actual Connect playback. CI generates a short
preview as a downloadable artifact on Python 3.14.

Run the behavioral checks separately:

```sh
uv sync --all-extras --group dev
uv run pytest tests/test_demo.py tests/test_session.py -q
```

These checks run the real pinned Strands `BidiAgent`, public tool hooks, shared retail tool, and A2A adapter. They observe multiple outgoing pulse frames while the tool remains pending, deliver another caller audio frame before the result, verify the contact update before the provider sees success, and cancel a 30-second lookup on disconnect. Other tests cover pause/resume through burst-delivered speech, continuous looping, quick-call silence, interruption, and bounded persistence waits. The demo settings are checked across OpenAI, Gemini, and Sonic apps; provider audio profiles are simulated offline.

For a live call, use Connect's tool trace start/end and returned audio to demonstrate the overlap. `strands.connect/audioSource` labels emitted audio artifacts as `tool_cue` or `model`; this is diagnostic metadata, not a promise that Contact details renders a separate cue track. Verify actual recording playback and indexed traces separately using the [deployment acceptance steps](deployment.md#6-acceptance-call).

Offline checks require no credentials or paid model calls. They do not establish live provider behavior, Connect recording playback, or that a hosted runtime has been updated. See [verification status](verification.md).
