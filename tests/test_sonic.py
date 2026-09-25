from strands.experimental.bidi.models.bedrock import BedrockNovaSonicModel

from examples.shared import application
from strands_connect.providers import make_model
from tests.fakes import INSTANCE


def test_nova_sonic_2_uses_native_strands_model_and_audio_profile():
    model = make_model("sonic", "amazon.nova-2-sonic-v1:0", region="us-east-1")
    assert isinstance(model, BedrockNovaSonicModel)
    assert model.get_config()["model_id"] == "amazon.nova-2-sonic-v1:0"
    assert model.get_audio_config() == {
        "input": {"sample_rate": 16000, "channels": 1, "format": "pcm"},
        "output": {"sample_rate": 24000, "channels": 1, "format": "pcm"},
    }


async def test_sonic_example_uses_aws_without_reading_provider_secrets(monkeypatch):
    monkeypatch.setenv("CONNECT_INSTANCE_ARN", INSTANCE)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("MODEL_SECRET_ARN", "must-not-be-read")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-used")
    monkeypatch.delenv("VOICE_MODEL", raising=False)
    connect_client = object()
    model = object()

    def client(service, **kwargs):
        assert service == "connect", "Sonic must not request a provider secret"
        return connect_client

    def model_factory(provider, model_id, **kwargs):
        assert provider == "sonic"
        assert model_id == "amazon.nova-2-sonic-v1:0"
        assert kwargs == {"api_key": None, "region": "us-east-1"}
        return model

    monkeypatch.setattr(application.boto3, "client", client)
    monkeypatch.setattr(application, "make_model", model_factory)
    monkeypatch.setattr(application, "create_agentcore_app", lambda factory, **kwargs: factory)
    monkeypatch.setattr(application, "configure_session", lambda socket, **kwargs: kwargs)
    session_factory = application.create_app("sonic", "amazon.nova-2-sonic-v1:0")
    session = await session_factory(object(), runtime_session_id="runtime-test")
    assert session["connect_client"] is connect_client
    assert session["instance_arn"] == INSTANCE
    assert session["runtime_session_id"] == "runtime-test"
    assert session["model_factory"]() is model
