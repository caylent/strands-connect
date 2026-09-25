# Connect + Gemini Live + Strands + AgentCore

From the repository root:

```sh
uv sync --extra gemini --extra agentcore
export CONNECT_INSTANCE_ARN='your-connect-instance-arn'
export AWS_REGION='us-east-1'
# Supply GEMINI_API_KEY securely in your environment, or MODEL_SECRET_ARN.
uv run python -m examples.connect_gemini.app
```

The app exposes `/ws` on port 8080. Set `VOICE_MODEL` to override `gemini-3.1-flash-live-preview`. It negotiates 16 kHz PCM16 mono input and 24 kHz output. It retains the tool-call-name and spoken-transcript fixes from the originating Gemini demo; see [provider notes](../../docs/providers.md).

The synthetic retail tools, result mapping, contact attributes, lifecycle, and optional tool sounds are identical to the OpenAI example. There is no provider-specific persistence code. Set `TOOL_CUE_ENABLED=false` to disable the default soft-pulse waiting sound.

For real Connect calls, follow [deployment and registration](../../docs/deployment.md). The original Gemini prototype was live-tested; this extracted package's changes still require the new acceptance call documented in [verification](../../docs/verification.md).
