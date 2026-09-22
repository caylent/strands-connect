import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from examples.shared import bridge
from strands_connect.session import EXT


async def test_bridge_authentication_and_runtime_session_forwarding(monkeypatch):
    captured, ready = {}, asyncio.Event()

    async def runtime_peer(ws):
        captured["context"] = json.loads(await ws.recv())
        await ws.send(await ws.recv())

    async with serve(runtime_peer, "127.0.0.1", 0) as runtime:
        runtime_url = f"ws://127.0.0.1:{runtime.sockets[0].getsockname()[1]}"

        def generate(**kwargs):
            captured["signed"] = kwargs
            return runtime_url, {"Authorization": "signed-test", "Host": "must-be-filtered"}

        monkeypatch.setattr(
            bridge,
            "AgentCoreRuntimeClient",
            lambda **kwargs: SimpleNamespace(
                generate_ws_connection=generate,
            ),
        )
        monkeypatch.setenv("ADAPTER_BEARER_TOKEN", "fixture-only")
        monkeypatch.setenv("AGENTCORE_RUNTIME_ARN", "test-runtime")
        monkeypatch.setenv("PORT", "0")

        @asynccontextmanager
        async def capture_server(*args, **kwargs):
            async with serve(*args, **kwargs) as server:
                captured["port"] = server.sockets[0].getsockname()[1]
                ready.set()
                yield server

        monkeypatch.setattr(bridge, "serve", capture_server)
        task = asyncio.create_task(bridge.main())
        try:
            await asyncio.wait_for(ready.wait(), 2)
            url = f"ws://127.0.0.1:{captured['port']}/a2a"
            with pytest.raises(InvalidStatus) as denied:
                async with connect(url, proxy=None):
                    pass
            assert denied.value.response.status_code == 401
            async with connect(
                url,
                proxy=None,
                additional_headers={
                    "Authorization": "Bearer fixture-only",
                    "traceparent": "trace",
                },
            ) as ws:
                assert ws.response.headers["A2A-Extensions"] == EXT
                await ws.send('{"hello":true}')
                assert json.loads(await asyncio.wait_for(ws.recv(), 2)) == {"hello": True}
            assert captured["signed"]["runtime_arn"] == "test-runtime"
            assert captured["context"]["runtime_session_id"] == captured["signed"]["session_id"]
            assert captured["context"]["headers"] == {"traceparent": "trace"}
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
