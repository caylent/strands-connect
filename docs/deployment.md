# AgentCore + Strands + Amazon Connect setup

The package is account-independent. The examples assume an existing Connect instance and a dedicated test flow/number. Nothing in installation or CI creates AWS resources. The following commands deliberately deploy resources in **your** selected AWS account.

## 1. Run an example locally

Clone the repository and follow one of the three example READMEs. Each exposes the AgentCore WebSocket application at `/ws` on port 8080, using exactly the same entrypoint as the hosted runtime. Local AgentCore server mode does not provide IAM authentication: keep it on a trusted machine/network and do not expose it directly to Connect or the Internet.

OpenAI and Gemini keys may come from environment variables locally. For their deployments, create a Secrets Manager secret whose `SecretString` is the raw provider API key; do not put a JSON object or an API key in source files, CloudFormation parameters, or contact attributes. Nova 2 Sonic uses the AWS credential chain/runtime role and requires no model secret.

## 2. Package and deploy AgentCore

Build a Linux ARM64 Python 3.14 artifact without Docker:

```sh
uv run python scripts/package_agentcore.py --provider openai
# Or: --provider gemini / --provider sonic
```

Select the intended AWS profile/region and set deployment variables in your shell. `CONNECT_INSTANCE_ARN`, `MODEL_SECRET_ARN`, `ASSETS_BUCKET`, and `CODE_KEY` refer to resources you own. Use a versioned/unique object key and a private S3 bucket in the runtime's region.

```sh
aws s3 cp build/openai/agentcore.zip "s3://$ASSETS_BUCKET/$CODE_KEY"
aws cloudformation deploy \
  --template-file deployment/agentcore.json \
  --stack-name strands-connect-openai \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    RuntimeName=strands_connect_openai \
    VoiceProvider=openai VoiceModel=gpt-realtime \
    ConnectInstanceArn="$CONNECT_INSTANCE_ARN" \
    ModelSecretArn="$MODEL_SECRET_ARN" \
    AssetsBucket="$ASSETS_BUCKET" CodeKey="$CODE_KEY"
```

For Gemini, upload `build/gemini/agentcore.zip`, choose distinct stack/runtime names, and set `VoiceProvider=gemini VoiceModel=gemini-3.1-flash-live-preview`. Override model names to an available compatible model. If the secret uses a customer-managed KMS key, supply `SecretKeyArn` and authorize the runtime role in that key's policy. If the artifact bucket uses a customer-managed key, grant decryption separately.

For Nova 2 Sonic, follow the [dedicated example](../examples/connect_nova_sonic_2/README.md): upload `build/sonic/agentcore.zip`, set `VoiceProvider=sonic VoiceModel=amazon.nova-2-sonic-v1:0`, and omit `ModelSecretArn` / `SecretKeyArn`. The provider parameter must match the packaged example.

The template creates the Python 3.14 runtime and execution role. It grants contact attribute read/write and contact description read within the configured Connect instance, access to the exact code artifact, and runtime logging. OpenAI/Gemini receive access to their configured secret; Sonic receives `bedrock:InvokeModelWithBidirectionalStream` for the selected model, without provider-secret permissions. It does not create a Connect instance, change flows, enable recordings, configure retention, or deploy an Internet ingress.

To enable the optional name/description tool, set `allow_contact_details=True` in your application policy and add `connect:UpdateContact` on the configured instance's contact resources. The Sonic template branch already includes the scoped Bedrock invocation permission.

## 3. Provide authenticated Connect ingress

Connect external applications use a bearer-authenticated WebSocket; AgentCore uses IAM/SigV4 (or its separately configured OAuth mode). The included thin bridge translates that authentication boundary and forwards A2A frames. It does not run the agent.

```sh
export AGENTCORE_RUNTIME_ARN='your-runtime-arn'
export ADAPTER_SECRET_ARN='your-connect-bearer-secret-arn'
uv run python -m examples.shared.bridge
```

The bridge listens on port 8080 at `/a2a`; set `PORT` to change it. For local testing only, `ADAPTER_BEARER_TOKEN` can replace the secret lookup. Production ingress must terminate TLS, expose `wss://.../a2a`, preserve the authorization and A2A extension headers, support long-lived WebSockets, and restrict direct access to the bridge. A reverse proxy or your existing ingress service can supply this; the repository does not provision it yet.

The bridge's role needs `secretsmanager:GetSecretValue` for its bearer secret (and KMS permission when applicable), plus `bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream` for the chosen runtime. Each accepted contact receives a fresh runtime session UUID; never reuse a runtime session across contacts. The runtime independently validates the Connect contact before opening a model connection.

AWS also documents direct AgentCore collaborators. Native audio was rejected for an AI-agent handoff target in the originating prototype's account. Validate support in your account before removing the bridge; do not assume a generic AgentCore URL implements Connect's voice extensions. The external application path is the documented example here.

## 4. Configure the Connect collaborator and flow

Follow AWS's [external collaborator setup](https://docs.aws.amazon.com/connect/latest/adminguide/a2a-setup-external.html):

1. Register the external application against your WSS `/a2a` endpoint, with the matching bearer secret and Connect A2A extension.
2. Configure native audio streaming on the external application handoff target.
3. Use the documented Lex V2 / Nova Sonic prerequisites and immediate handoff configuration. During the external session, the selected provider generates the response audio.
4. Add the AI-agent invocation to a dedicated test flow. Configure `COMPLETE` and `ESCALATE` outcomes; escalation only reaches a human if **your flow** routes to a staffed queue.
5. After handback, read `OrderId`, `OrderStatus`, `AgentDisposition`, `AgentHandoffNote`, and `AgentPersistenceState` as user-defined attributes. Do not treat incomplete state as success.
6. Associate only the intended test number/channel after reviewing the flow. Do not replace a production flow to try this example.

[Voice constraints](https://docs.aws.amazon.com/connect/latest/adminguide/a2a-voice.html) apply: negotiated audio mode is fixed; completion/escalation ends that collaboration session.

## 5. Enable and verify interaction history separately

Configure automated interaction logging, bot analytics/transcripts, storage destinations, and permissions according to [AI-agent traces](https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-traces.html). The adapter emits per-turn transcript and tool spans when `subscribeToTracingEvents=true`; emitting them is not proof of indexing in Contact details.

For recordings, configure Connect recording storage and enable recording for the intended IVR portion in the test flow. Validate actual recording playback. An application audit JSON or AgentCore log is not a substitute for a Connect recording or contact transcript.

## 6. Acceptance call

Ask for order **1042**, interrupt an answer, ask for order status again, then say goodbye. Verify returned audio, both transcripts, tool request/result traces, `OrderStatus=Shipped`, a completed disposition, subsequent flow readback, and recording playback. Repeat with an escalation request and a brief note, then run two concurrent contacts to check isolation. Repeat with each provider using the same mapping/tools.

Exercise provider failure and denied attribute writes; they must not produce an unverified success. Keep test contact IDs and results in your own private evidence store, not this public repository.

## References

- [AgentCore supported Python runtimes](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CodeConfiguration.html)
- [AgentCore WebSocket runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html)
- [Connect A2A protocol](https://docs.aws.amazon.com/connect/latest/devguide/a2a-developer-guide.html)
- [Direct collaborators](https://docs.aws.amazon.com/connect/latest/adminguide/a2a-setup-1p.html)
