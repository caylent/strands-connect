"""Example-specific model/secret setup, using the library's AgentCore app factory."""

import asyncio
import os

import boto3
from botocore.config import Config

from strands_connect.agentcore import create_app as create_agentcore_app
from strands_connect.providers import make_model

from .retail import configure_session, validate_tool_delay

AWS_CONFIG = Config(connect_timeout=3, read_timeout=4, retries={"max_attempts": 2, "mode": "standard"})


def create_app(provider, default_model):
    # Fail at startup for a bad setting, before accepting a caller or opening a model.
    demo_tool_delay = validate_tool_delay(os.getenv("DEMO_TOOL_DELAY_SECONDS", "8"))

    async def session_factory(socket, *, runtime_session_id):
        region = os.getenv("AWS_REGION", "us-east-1")
        api_key = None
        if provider != "sonic":
            api_key = os.getenv("OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY")
            if os.getenv("MODEL_SECRET_ARN"):
                sm = boto3.client("secretsmanager", region_name=region, config=AWS_CONFIG)
                api_key = (
                    await asyncio.to_thread(
                        sm.get_secret_value,
                        SecretId=os.environ["MODEL_SECRET_ARN"],
                    )
                )["SecretString"]
        connect = boto3.client("connect", region_name=region, config=AWS_CONFIG)
        return configure_session(
            socket,
            connect_client=connect,
            instance_arn=os.environ["CONNECT_INSTANCE_ARN"],
            provider=provider,
            runtime_session_id=runtime_session_id,
            model_factory=lambda: make_model(
                provider,
                os.getenv("VOICE_MODEL", default_model),
                api_key=api_key,
                region=region,
            ),
            cue_enabled=os.getenv("TOOL_CUE_ENABLED", "true").lower() == "true",
            demo_tool_delay_seconds=demo_tool_delay,
        )

    return create_agentcore_app(session_factory, service_name="strands-connect-" + provider)
