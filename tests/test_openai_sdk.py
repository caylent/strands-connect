"""Use the real OpenAI SDK against a local WebSocket fixture; no external key or spend."""

import asyncio
import json

from openai import AsyncOpenAI
from websockets.asyncio.server import serve

from strands_connect.providers import openai as provider


async def test_official_sdk_session_audio_tools_and_cleanup(monkeypatch):
    received = []

    async def peer(ws):
        assert "model=gpt-realtime" in ws.request.path
        assert ws.request.headers["Authorization"] == "Bearer test-only"
        async for raw in ws:
            request = json.loads(raw)
            received.append(request)
            if request["type"] == "session.update":
                await ws.send(json.dumps({"type": "response.output_audio.delta", "delta": "AAA="}))
                await ws.send(
                    json.dumps(
                        {
                            "type": "response.output_item.added",
                            "item": {
                                "type": "function_call",
                                "call_id": "call-123",
                                "name": "lookup_order",
                            },
                        }
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "type": "response.function_call_arguments.delta",
                            "call_id": "call-123",
                            "delta": '{"order_id":"1042"}',
                        }
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "type": "response.function_call_arguments.done",
                            "call_id": "call-123",
                            "name": "lookup_order",
                            "arguments": '{"order_id":"1042"}',
                        }
                    )
                )

    async with serve(peer, "127.0.0.1", 0) as server:
        client = AsyncOpenAI(
            api_key="test-only", websocket_base_url=(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        )
        monkeypatch.setattr(provider, "AsyncOpenAI", lambda **kwargs: client)
        model = provider.OpenAIRealtimeSDKModel(model_id="gpt-realtime", api_key="test-only")
        try:
            await model.start(
                system_prompt="Help the caller.",
                tools=[
                    {
                        "name": "lookup_order",
                        "description": "Look up an order",
                        "inputSchema": {
                            "json": {"type": "object", "properties": {"order_id": {"type": "string"}}}
                        },
                    }
                ],
            )
            stream = model.receive()
            assert (await asyncio.wait_for(anext(stream), 3))["type"] == "bidi_connection_start"
            audio = await asyncio.wait_for(anext(stream), 3)
            assert audio["type"] == "bidi_audio_stream" and audio["sample_rate"] == 24000
            tool = await asyncio.wait_for(anext(stream), 3)
            assert tool["current_tool_use"]["name"] == "lookup_order"
            assert tool["current_tool_use"]["input"] == {"order_id": "1042"}
            await stream.aclose()
        finally:
            await model.stop()
        assert client.is_closed()
    session = received[0]["session"]
    assert session["type"] == "realtime" and session["instructions"] == "Help the caller."
    assert session["audio"]["input"]["format"]["rate"] == 24000
    assert session["tools"][0]["name"] == "lookup_order"
