import uuid

from starlette.testclient import TestClient

from strands_connect.agentcore import create_app


def test_runtime_health_does_not_create_model_or_contact():
    def factory(*args, **kwargs):
        raise AssertionError("Health must not create a contact session")

    with TestClient(create_app(factory)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "health"})
            assert ws.receive_json() == {"service": "strands-connect", "transport": "/ws"}


def test_runtime_forwards_authenticated_context_and_first_protocol_frame():
    seen = []
    runtime_id = str(uuid.uuid4())

    class Session:
        def __init__(self, socket):
            self.socket = socket

        async def run(self):
            seen.append(await anext(self.socket))
            await self.socket.send('{"ok":true}')

    async def factory(socket, *, runtime_session_id):
        seen.append((runtime_session_id, socket.headers.get("traceparent")))
        return Session(socket)

    with TestClient(create_app(factory)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "type": "bridge_context",
                    "runtime_session_id": runtime_id,
                    "headers": {"traceparent": "trace", "untrusted": "ignored"},
                }
            )
            ws.send_json({"method": "SendMessage"})
            assert ws.receive_json() == {"ok": True}
    assert seen[0] == (runtime_id, "trace")
    assert "SendMessage" in seen[1]


def test_runtime_supports_first_frame_without_bridge_envelope():
    class Session:
        def __init__(self, socket):
            self.socket = socket

        async def run(self):
            await self.socket.send(await anext(self.socket))

    with TestClient(create_app(lambda socket, **kwargs: Session(socket))) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"method": "SendMessage"})
            assert ws.receive_json() == {"method": "SendMessage"}
