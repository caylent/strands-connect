"""Lazy optional-provider imports. Any compatible BidiModel can also be injected."""


def make_model(provider: str, model_id: str, *, api_key=None, region="us-east-1", voice=None):
    if provider == "openai":
        from .openai import OpenAIRealtimeSDKModel

        return OpenAIRealtimeSDKModel(model_id=model_id, api_key=api_key, voice=voice or "marin")
    if provider == "gemini":
        from .gemini import GeminiLiveModel

        return GeminiLiveModel(
            model_id=model_id,
            client_args={"api_key": api_key},
            audio={"input": {"sample_rate": 16000}},
            voice=voice or "Aoede",
        )
    if provider == "sonic":
        from strands.experimental.bidi.models.bedrock import BedrockNovaSonicModel

        return BedrockNovaSonicModel(
            model_id=model_id,
            region=region,
            audio={"input": {"sample_rate": 16000}, "output": {"sample_rate": 24000}},
        )
    raise ValueError("Unknown provider; use openai, gemini, sonic, or inject your own BidiModel")
