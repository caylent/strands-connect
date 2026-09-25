"""Demo settings and actual BidiAgent execution during a slow business tool."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from examples.shared import application, retail
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


@pytest.mark.parametrize("value", ["", "slow", "nan", "inf", "-1", "30.01", None, True])
def test_invalid_delay_is_rejected(value):
    with pytest.raises(ValueError, match="finite number from 0 to 30"):
        retail.validate_tool_delay(value)


@pytest.mark.parametrize("value,expected", [("0", 0), ("8", 8), ("1.5", 1.5), (30, 30)])
def test_delay_range(value, expected):
    assert retail.validate_tool_delay(value) == expected


@pytest.mark.parametrize("provider", ["openai", "gemini", "sonic"])
@pytest.mark.parametrize("setting,expected", [(None, 8), ("0", 0), ("15", 15)])
async def test_examples_apply_operator_delay(provider, setting, expected, monkeypatch):
    monkeypatch.delenv("DEMO_TOOL_DELAY_SECONDS", raising=False)
    if setting is not None:
        monkeypatch.setenv("DEMO_TOOL_DELAY_SECONDS", setting)
    monkeypatch.delenv("MODEL_SECRET_ARN", raising=False)
    monkeypatch.setenv("CONNECT_INSTANCE_ARN", INSTANCE)
    monkeypatch.setattr(application.boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(application, "create_agentcore_app", lambda factory, **kwargs: factory)
    monkeypatch.setattr(application, "configure_session", lambda socket, **kwargs: kwargs)
    factory = application.create_app(provider, "unused")
    settings = await factory(object(), runtime_session_id="demo")
    assert settings["demo_tool_delay_seconds"] == expected


def test_invalid_delay_fails_before_app_starts(monkeypatch):
    monkeypatch.setenv("DEMO_TOOL_DELAY_SECONDS", "nan")
    with pytest.raises(ValueError, match="DEMO_TOOL_DELAY_SECONDS"):
        application.create_app("sonic", "unused")


@pytest.mark.parametrize("provider,rate", [("openai", 24000), ("gemini", 16000), ("sonic", 16000)])
async def test_delayed_tool_overlaps_audio_and_incoming_stream(provider, rate):
    socket, client = MemorySocket(), ContactClient()
    model = WaitingModel(client, rate)
    session = retail.configure_session(
        socket,
        connect_client=client,
        model_factory=lambda: model,
        instance_arn=INSTANCE,
        provider=provider,
        demo_tool_delay_seconds=1.8,
    )
    await socket.incoming.put(init_frame())
    await socket.incoming.put(frame("CHANNEL_STATE", {"channelState": {"state": "READY"}}))
    await socket.incoming.put(audio_input())
    task = asyncio.create_task(session.run())
    cue_times = []
    try:
        async with asyncio.timeout(5):
            while len(cue_times) < 5:
                response = await socket.outgoing.get()
                if audio_source(response) == "tool_cue":
                    cue_times.append(time.monotonic())
            assert session.pending_tools and not model.result_received.is_set()
            assert "OrderStatus" not in client.attributes.get(CONTACT, {})
            # The caller can still send audio while the tool AND cue are running.
            await socket.incoming.put(audio_input())
            await model.input_during_wait.wait()
            assert not model.result_received.is_set()
            await model.result_received.wait()
            assert cue_times[-1] < model.result_at
            assert client.attributes[CONTACT]["OrderStatus"] == "Shipped"
            assert len(model.calls) == 1
            # Model speech resumes after the mapped result has been saved.
            while audio_source(await socket.outgoing.get()) != "model":
                pass
    finally:
        await socket.incoming.put(None)
        await asyncio.wait_for(task, 3)
    assert model.stopped and not session.pending_tools and session.cue_task is None


async def test_disconnect_cancels_delayed_lookup_without_late_order_write(monkeypatch):
    socket, client = MemorySocket(), ContactClient()
    model = WaitingModel(client, 16000)
    computed = []
    cancelled = asyncio.Event()
    original = retail.order_result

    async def observed_sleep(delay):
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def observe(order_id):
        computed.append(order_id)
        return original(order_id)

    monkeypatch.setattr(retail, "order_result", observe)
    monkeypatch.setattr(retail, "asyncio", SimpleNamespace(sleep=observed_sleep))
    session = retail.configure_session(
        socket,
        connect_client=client,
        model_factory=lambda: model,
        instance_arn=INSTANCE,
        provider="test",
        demo_tool_delay_seconds=30,
    )
    await socket.incoming.put(init_frame())
    await socket.incoming.put(frame("CHANNEL_STATE", {"channelState": {"state": "READY"}}))
    await socket.incoming.put(audio_input())
    task = asyncio.create_task(session.run())
    try:
        async with asyncio.timeout(3):
            while audio_source(await socket.outgoing.get()) != "tool_cue":
                pass
    finally:
        await socket.incoming.put(None)
        await asyncio.wait_for(task, 2)
    assert model.stopped and not model.result_received.is_set()
    assert cancelled.is_set() and not computed and session.cue_task is None
    # Strands does not run AfterToolCallEvent for task cancellation. The unfinished
    # record remains in the session audit; it is not an executing business tool.
    assert "OrderStatus" not in client.attributes[CONTACT]
    assert client.attributes[CONTACT]["AgentPersistenceState"] == "disconnected"
