# Voice providers

| Provider | Extension | Audio | Status |
|---|---|---|---|
| OpenAI Realtime | `OpenAIRealtimeSDKModel` | 24 kHz input/output | Runnable example; real SDK exercised against a local protocol server |
| Google Gemini Live | `GeminiLiveModel` | 16 kHz input / 24 kHz output | Runnable example; compatibility fixes extracted from a live-tested prototype |
| Amazon Nova 2 Sonic | Strands `BedrockNovaSonicModel` | 16 kHz input / 24 kHz output | [Runnable AgentCore example](../examples/connect_nova_sonic_2/README.md); IAM authentication; offline coverage, live acceptance pending |
| Other native voice providers | Inject a `BidiModel` with `get_audio_config()` | PCM16 mono at 8/16/24 kHz | Supported extension seam, not a claim of provider compatibility |

Ordinary text-only model providers do not automatically become native voice providers. A text-model + speech-recognition + speech-synthesis pipeline would need another `BidiModel` implementation, including interruption behavior. Azure-hosted OpenAI, speech vendors, and SIP-native integrations need their own authentication/audio/lifecycle contract tests before being listed as supported.

## OpenAI

The example uses the **official Python OpenAI SDK** (`AsyncOpenAI.realtime.connect`) to connect to the Realtime API. It reuses Strands' OpenAI provider's event conversion, tool schemas, VAD events, and history replay. Strands remains the agent/tool runtime; it does not nest an OpenAI Agents SDK `RealtimeAgent` inside Strands.

Strands 1.56's stock OpenAI provider connects directly through `websockets`. To honor the SDK example, a small subclass replaces connection setup and delegates send/receive/close to the official SDK. This touches private Strands configuration/history methods and is isolated in `providers/openai.py`, pinned and tested. A future public Strands connection factory could remove that seam.

`gpt-realtime` is the configurable example default; it is not a claim to be the latest model. Set `VOICE_MODEL` to a Realtime model available to your account. OpenAI keys stay on the server. The SDK and Strands share a compatible WebSocket dependency; SDK connection retries are disabled so Strands owns reconnect/replay.

## Gemini

The example retains the prototype's `gemini-3.1-flash-live-preview` default; override `VOICE_MODEL` for an available compatible model. Two version-specific fixes remain isolated in `providers/gemini.py`: preserve the function name separately from its call ID, and use output transcription rather than model thought/text parts for spoken history. Contract tests cover both. Review/remove these overrides when upgrading Strands; do not patch SDK globals.

The earlier prototype encountered provider closure errors with a Gemini 2.5 native-audio model during tool calls. That is historical evidence, not a claim about all current 2.5 sessions. Test the exact model and account before changing defaults.

## Nova 2 Sonic and custom providers

```python
model_factory = lambda: make_model("sonic", "amazon.nova-2-sonic-v1:0", region="us-east-1")
```

Pass `voice="tiffany"` (or another voice supported by your selected model) to `make_model` to choose the Sonic output voice. If omitted, the factory uses `matthew`. The value is forwarded to Strands and included in the provider's audio-output configuration.

Install the `sonic` and `agentcore` extras. The dedicated example uses `amazon.nova-2-sonic-v1:0`. Set `VoiceProvider=sonic` in the deployment template to grant the relevant Bedrock bidirectional model permission and omit model-secret access. No external API key is needed. Python 3.14 is the default for development and AgentCore code packaging. To add another provider, implement the public Strands `BidiModel` contract and audio configuration; inject a fresh instance per contact. Keep contact persistence and business-result mappings unchanged.

## Sources

- [Strands realtime hooks](https://strandsagents.com/docs/user-guide/sdk/bidirectional-streaming/hooks/)
- [Strands OpenAI provider](https://strandsagents.com/docs/user-guide/sdk/bidirectional-streaming/models/openai/)
- [OpenAI Realtime API](https://developers.openai.com/api/docs/guides/realtime)
- [Gemini Live tools](https://ai.google.dev/gemini-api/docs/live-api/tools)
