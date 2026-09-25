# Connect + Amazon Nova 2 Sonic + Strands + AgentCore

Use Python **3.14** (the repository default). From the repository root:

```sh
uv sync --extra sonic --extra agentcore
export CONNECT_INSTANCE_ARN='your-connect-instance-arn'
export AWS_REGION='us-east-1'
# Locally, select your authorized AWS profile/SSO session or another normal AWS credential source.
uv run python -m examples.connect_nova_sonic_2.app
```

The app exposes `/ws` on port 8080 and uses `amazon.nova-2-sonic-v1:0` through Strands' `BedrockNovaSonicModel`. It negotiates 16 kHz PCM16 mono input and 24 kHz output. `VOICE_MODEL` can override the model ID when you have a compatible model and matching permission.

**Authentication is AWS IAM.** The Strands provider uses boto3's credential chain locally and the execution role on AgentCore. No OpenAI/Gemini API key or `MODEL_SECRET_ARN` is needed; this example ignores external-provider secret configuration. The role needs `bedrock:InvokeModelWithBidirectionalStream` on the Nova 2 Sonic model in the selected supported AWS region, plus the same scoped Connect permissions as the other examples.

The order lookup, deterministic contact persistence, transcript/tool tracing, completion/escalation, and optional tool sounds are shared with OpenAI and Gemini. Set `TOOL_CUE_ENABLED=false` to disable the earcon. Connect's Lex/Sonic prerequisite remains a separate setup step; the external Nova 2 Sonic model generates the audio returned by this example.

## Package and deploy

```sh
uv run python scripts/package_agentcore.py --provider sonic
aws s3 cp build/sonic/agentcore.zip "s3://$ASSETS_BUCKET/$CODE_KEY"
aws cloudformation deploy \
  --template-file deployment/agentcore.json \
  --stack-name strands-connect-sonic \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    RuntimeName=strands_connect_sonic \
    VoiceProvider=sonic VoiceModel=amazon.nova-2-sonic-v1:0 \
    ConnectInstanceArn="$CONNECT_INSTANCE_ARN" \
    AssetsBucket="$ASSETS_BUCKET" CodeKey="$CODE_KEY"
```

The template uses `PYTHON_3_14` and grants Bedrock access for the configured model only when `VoiceProvider=sonic`. Use the same provider for the code artifact and template parameter. Follow [Connect and AgentCore setup](../../docs/deployment.md) to configure the authenticated bridge, collaborator, test flow, and recording/transcript settings.

The bridge's bearer secret authenticates Connect ingress and is still required; it is separate from a model provider secret. Escalation reaches a human only if your Connect flow routes to a staffed queue.

[Verification](../../docs/verification.md) distinguishes offline tests and packaging from live Bedrock/Connect acceptance. This example has not yet been deployed or live-call tested as part of this update.

## AWS references

- [Nova 2 Sonic model](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-sonic.html)
- [Speech-to-speech setup](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-getting-started.html)
