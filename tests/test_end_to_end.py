"""Offline protocol acceptance through actual BidiAgent, tool executor, and hooks."""

import asyncio
import base64
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from examples.shared.retail import configure_session
from strands_connect.session import EXT, pcm_config
from tests.fakes import CONTACT, INSTANCE, ContactClient, MemorySocket, ScriptedModel


def frame(kind, data=None, parts=None, context="collaboration"):
    return {
        "jsonrpc": "2.0",
        "id": "request",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "message",
                "contextId": context,
                "role": "ROLE_USER",
                "parts": parts or [{"data": data}],
                "metadata": {EXT + "/eventType": kind},
            }
        },
    }


def init_frame():
    return frame(
        "INIT_SESSION",
        {
            "initSession": {
                "instanceArn": INSTANCE,
                "contactArn": INSTANCE + "/contact/" + CONTACT,
                "audioInputConfiguration": pcm_config(8000),
                "supportedFinishTypes": ["COMPLETE", "ESCALATE"],
                "subscribeToTracingEvents": True,
                "history": [{"role": "ROLE_USER", "parts": [{"text": "I need order help."}]}],
            }
        },
    )


@pytest.mark.parametrize("provider,rate", [("openai", 24000), ("gemini", 16000)])
@pytest.mark.parametrize(
    "finish_type,closing,disposition",
    [("COMPLETE", "goodbye", "completed"), ("ESCALATE", "human", "escalated")],
)
async def test_both_provider_profiles_over_websocket(provider, rate, finish_type, closing, disposition):
    client = ContactClient()
    model = ScriptedModel(client, rate=rate)
    sessions = []

    async def handler(ws):
        class Socket:
            headers = dict(ws.request.headers)

            def __aiter__(self):
                return ws.__aiter__()

            async def send(self, payload):
                await ws.send(payload)

            async def close(self):
                await ws.close()

        s = configure_session(
            Socket(),
            connect_client=client,
            model_factory=lambda: model,
            instance_arn=INSTANCE,
            provider=provider,
            cue_enabled=False,
        )
        sessions.append(s)
        await s.run()

    async with serve(handler, "127.0.0.1", 0) as server:
        async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", proxy=None) as ws:
            await ws.send(json.dumps(init_frame()))
            response = json.loads(await asyncio.wait_for(ws.recv(), 3))
            config = response["result"]["message"]["parts"][0]["data"]["initSessionResponse"]
            assert config["audioInputConfiguration"]["sampleRateHertz"] == rate
            assert model.messages[0]["content"][0]["text"] == "I need order help."
            await ws.send(json.dumps(frame("CHANNEL_STATE", {"channelState": {"state": "READY"}})))
            await ws.send(
                json.dumps(
                    frame(
                        "AUDIO_INPUT",
                        parts=[
                            {
                                "raw": base64.b64encode(b"\x00\x00" * 160).decode(),
                                "mediaType": "audio/lpcm",
                            }
                        ],
                    )
                )
            )
            frames = []
            async with asyncio.timeout(5):
                async for raw in ws:
                    response = json.loads(raw)
                    frames.append(response)
                    status = response.get("result", {}).get("statusUpdate")
                    if not status:
                        continue
                    assert status["status"]["state"] == "TASK_STATE_COMPLETED", response
                    if "message" in status["status"]:
                        assert (
                            status["status"]["message"]["parts"][0]["data"]["finish"]["type"] == finish_type
                        )
                        break
                    await ws.send(json.dumps(frame("TEXT", parts=[{"text": closing}])))
        assert sessions[0].finished_sent
    actual = client.attributes[CONTACT]
    assert actual["OrderId"] == "1042" and actual["OrderStatus"] == "Shipped"
    assert actual["AgentDisposition"] == disposition and actual["AgentPersistenceState"] == "complete"
    assert model.stopped and not sessions[0].failed
    assert "TRACING_SPAN" in json.dumps(frames)
    assert "execute_tool lookup_order" in json.dumps(frames)
    assert "artifactUpdate" in frames[-2]["result"]  # Trace arrives before final FINISH.


async def test_invalid_contact_fails_before_provider_connects():
    client, socket = ContactClient(), MemorySocket()
    model = ScriptedModel(client)
    s = configure_session(
        socket, connect_client=client, model_factory=lambda: model, instance_arn=INSTANCE, provider="test"
    )
    incoming = init_frame()
    incoming["params"]["message"]["parts"][0]["data"]["initSession"]["instanceArn"] = "foreign"
    await socket.incoming.put(incoming)
    await asyncio.wait_for(s.run(), 2)
    assert not model.started
    assert socket.closed and s.failed and socket.frames[0]["error"]


async def test_dtmf_complete_is_forwarded_as_text():
    socket = MemorySocket()
    client = ContactClient()
    model = ScriptedModel(client)
    s = configure_session(
        socket, connect_client=client, model_factory=lambda: model, instance_arn=INSTANCE, provider="test"
    )
    await socket.incoming.put(init_frame())
    await socket.incoming.put(frame("DTMF_INPUT_COMPLETE", {"dtmfInputComplete": {"inputString": "1234"}}))
    await socket.incoming.put(None)
    await asyncio.wait_for(s.run(), 2)
    assert any(e.get("text") == "Caller entered these digits: 1234" for e in model.inputs)
