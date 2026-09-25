# Connect + OpenAI Realtime SDK + Strands + AgentCore

From the repository root:

```sh
uv sync --extra openai --extra agentcore
export CONNECT_INSTANCE_ARN='your-connect-instance-arn'
export AWS_REGION='us-east-1'
# Supply OPENAI_API_KEY securely in your environment, or MODEL_SECRET_ARN.
uv run python -m examples.connect_openai_realtime.app
```

The app exposes `/ws` on port 8080. Set `VOICE_MODEL` to override `gpt-realtime`. It uses the official Python OpenAI SDK's Realtime connection, with Strands owning the agent and tool execution. Audio is negotiated as 24 kHz PCM16 mono in both directions.

The shared synthetic order 1042 returns `Shipped`. The hook automatically saves `OrderId`/`OrderStatus`. Completion and escalation save disposition and notes. Optional tool sounds are on; set `TOOL_CUE_ENABLED=false` to disable them.

For real Connect calls, follow [deployment and registration](../../docs/deployment.md), including AgentCore packaging, authenticated ingress, Lex prerequisites, and a dedicated Connect flow. A bare local `/ws` URL is not a registered Connect collaborator.

[Verification status](../../docs/verification.md): offline SDK/Strands/transport tests are separate from paid OpenAI and live Connect acceptance.

The order lookup intentionally waits **8 seconds** while the soft pulse plays and caller audio continues streaming. Set `DEMO_TOOL_DELAY_SECONDS=15` for a longer loop demonstration, or `0` to disable the artificial delay (allowed range: 0–30). This is a demo-only setting, not a tool argument. See the [demo walkthrough](../../docs/demo.md).
