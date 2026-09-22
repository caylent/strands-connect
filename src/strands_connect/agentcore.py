"""Reusable AgentCore WebSocket app for any configured ConnectSession.

Install the agentcore extra. The hosted service supplies authentication; local
AgentCore development mode must remain on a trusted machine/network.
"""

import asyncio
import contextlib
import inspect
import json
import logging
import uuid

from bedrock_agentcore import BedrockAgentCoreApp
from starlette.websockets import WebSocketDisconnect


class RuntimeSocket:
    """Adapt an AgentCore/Starlette WebSocket to ConnectSession's socket contract."""

    def __init__(self, ws, headers, first=None):
        self.ws, self.headers, self.first = ws, headers, first

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.first is not None:
            first, self.first = self.first, None
            return first
        try:
            return await self.ws.receive_text()
        except WebSocketDisconnect:
            raise StopAsyncIteration from None

    async def send(self, payload):
        await self.ws.send_text(payload)

    async def close(self):
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await self.ws.close()


def create_app(session_factory, *, service_name="strands-connect"):
    """Create a deployable BedrockAgentCoreApp with HTTP health and /ws transport.

    session_factory(socket, runtime_session_id=...) returns a fresh ConnectSession.
    It may be async to load secrets or application configuration. It must not reuse
    a session/model/contact store across connections. Call app.run() to serve.
    """
    app = BedrockAgentCoreApp()

    @app.entrypoint
    def health(payload, context):
        return {"service": service_name, "transport": "/ws"}

    @app.websocket
    async def voice(ws, context):
        await ws.accept()
        socket = RuntimeSocket(ws, dict(ws.headers))
        try:
            first = await asyncio.wait_for(ws.receive_text(), 30)
            envelope = json.loads(first)
            if envelope.get("type") == "health":
                await ws.send_json(health({}, context))
                return
            header_id = socket.headers.get("x-amzn-bedrock-agentcore-runtime-session-id")
            runtime_id = header_id or str(uuid.uuid4())
            if envelope.get("type") == "bridge_context":
                # Only IAM-authenticated runtime callers may supply this envelope.
                supplied_id = str(uuid.UUID(envelope["runtime_session_id"]))
                if header_id and supplied_id != header_id:
                    raise ValueError("Runtime session context mismatch")
                runtime_id = supplied_id
                socket.headers.update(
                    {
                        k: v
                        for k, v in envelope.get("headers", {}).items()
                        if k in ("traceparent", "tracestate")
                    }
                )
            else:
                socket.first = first
            session = session_factory(socket, runtime_session_id=runtime_id)
            if inspect.isawaitable(session):
                session = await session
            await session.run()
        except Exception as error:
            logging.getLogger(__name__).error("runtime_session_failed error_type=%s", type(error).__name__)
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close(code=1011, reason="Voice session failed")
        finally:
            await socket.close()

    return app
