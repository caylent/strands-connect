"""Official OpenAI Realtime SDK transport with Strands' existing event conversion.

The pinned Strands provider uses websockets directly. This small compatibility seam
reuses its audio/tool conversion and substitutes the official SDK's public connection
methods. It does not run a second Agents SDK agent or duplicate Strands' tool loop.
"""

import time
import uuid

from openai import AsyncOpenAI
from strands.experimental.bidi.models.openai import OpenAIRealtimeModel


class _SDKSocket:
    def __init__(self, connection, client):
        self.connection, self.client = connection, client

    async def recv(self):
        return await self.connection.recv_bytes()

    async def send(self, payload):
        await self.connection.send_raw(payload)

    async def close(self):
        try:
            await self.connection.close()
        finally:
            await self.client.close()


class OpenAIRealtimeSDKModel(OpenAIRealtimeModel):
    """A BidiModel using AsyncOpenAI.realtime.connect, mono PCM16 at 24 kHz.

    Upstream private state/config/history methods are intentionally confined here.
    Version pins and protocol contract tests must be reviewed before SDK upgrades.
    Strands owns reconnect/history replay; SDK reconnect/retry is disabled.
    """

    async def start(self, system_prompt=None, tools=None, messages=None, **kwargs):
        if self._connection_id:
            raise RuntimeError("Model is already started")
        client = AsyncOpenAI(
            api_key=self.api_key,
            organization=self.organization,
            project=self.project,
            timeout=20,
            max_retries=0,
        )
        connection = None
        try:
            connection = await client.realtime.connect(
                model=self.model_id,
                max_retries=0,
                websocket_connection_options={"max_size": 2**20, "max_queue": 32, "open_timeout": 20},
            ).enter()
            self._websocket = _SDKSocket(connection, client)
            self._connection_id = str(uuid.uuid4())
            self._start_time = int(time.time())
            self._function_call_buffer = {}
            await self._send_event(
                {
                    "type": "session.update",
                    "session": self._build_session_config(
                        system_prompt,
                        tools,
                    ),
                }
            )
            if messages:
                await self._add_conversation_history(messages)
        except BaseException:
            try:
                if connection:
                    await connection.close()
            finally:
                self._connection_id = None
                await client.close()
            raise
