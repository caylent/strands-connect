import asyncio
import base64
import json
import threading

from examples.shared.retail import order_result
from strands_connect.contact import ContactContext, ContactPolicy, ContactStore
from strands_connect.session import EXT, ConnectSession
from tests.fakes import ContactClient


class Socket:
    headers = {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}

    def __init__(self):
        self.frames = []

    async def send(self, payload):
        self.frames.append(json.loads(payload))


def session():
    s = ConnectSession(
        Socket(),
        instance_arn="unused",
        connect_client=None,
        model_factory=None,
        tools_factory=None,
        system_prompt="unused",
    )
    s.context = "c"
    s.subscribe_to_traces = True
    s.contact = ContactContext("i", "c", "c", "context", "runtime")
    s.model_id = "test-model"
    return s


async def test_no_audio_before_ready():
    s = session()
    task = asyncio.create_task(s.output_audio(b"\x00\x00" * 100))
    await asyncio.sleep(0.01)
    assert s.socket.frames == []
    s.ready.set()
    await task
    assert len(s.socket.frames) == 1


async def test_interruption_cancels_tone_and_marks_partial_playback():
    s = session()
    s.ready.set()
    s.pending_tools["tool"] = {
        "id": "1" * 32,
        "name": "lookup_order",
        "arguments": {},
        "started": 1,
        "initiated_task": "old",
    }
    s.cue_task = asyncio.create_task(s.cue_loop())
    await asyncio.sleep(0.055)
    assert len(s.socket.frames) > 0
    s.audio_generation += 1
    await s.stop_cue()
    count = len(s.socket.frames)
    await asyncio.sleep(0.04)
    assert len(s.socket.frames) == count
    s.turn["output"] = "An interrupted answer"
    await s.finish_turn(interrupted=True)
    artifacts = [f["result"]["artifactUpdate"] for f in s.socket.frames if "artifactUpdate" in f["result"]]
    audio = [a for a in artifacts if a["artifact"]["metadata"][EXT + "/eventType"] == "AUDIO_RESPONSE_CHUNK"]
    assert all(not a["lastChunk"] for a in audio)
    assert s.history[0]["interrupted"] is True
    trace = artifacts[-1]["artifact"]["parts"][0]["data"]["tracingSpan"]["otlp"]
    spans = trace["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert any(e["name"] == "strands.connect.audio.interrupted" for e in spans[0]["events"])


async def test_final_transcript_trace_precedes_terminal_and_keeps_tool_result():
    s = session()
    s.ensure_turn().update(input="Where is order 1042?", output="Shipped.")
    s.completed_tools.append(
        {
            "id": "a" * 32,
            "name": "lookup_order",
            "arguments": {"order_id": "1042"},
            "started": 1,
            "ended": 2,
            "initiated_task": s.turn["task_id"],
            "result": {"status": "Shipped"},
            "status": "ok",
        }
    )
    await s.finish_turn()
    assert "artifactUpdate" in s.socket.frames[-2]["result"]
    assert "statusUpdate" in s.socket.frames[-1]["result"]
    otlp = s.socket.frames[-2]["result"]["artifactUpdate"]["artifact"]["parts"][0]["data"]["tracingSpan"][
        "otlp"
    ]
    spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert spans[0]["traceId"] == "a" * 32 and spans[0]["parentSpanId"] == "b" * 16
    assert spans[-1]["name"] == "execute_tool lookup_order"
    assert "Shipped" in json.dumps(spans[-1]["events"])


async def test_large_frames_reassemble_without_audio_fragmentation():
    s = session()
    result = {"message": {"text": "x" * 70000}}
    await s.send(result, "request-id")
    fragments = [f["result"]["message"]["parts"][0]["data"]["fragment"] for f in s.socket.frames]
    frame = json.loads(base64.b64decode("".join(f["payload"] for f in fragments)))
    assert frame["result"] == result and frame["id"] == "request-id"
    assert all(len(json.dumps(f)) < 24000 for f in s.socket.frames)


def test_unknown_order_is_not_fabricated():
    assert order_result("1042")["status"] == "Shipped"
    assert order_result("9999")["found"] is False


async def test_final_contact_write_and_drain_share_cleanup_deadline():
    s = session()
    s.contact_policy = ContactPolicy(write_timeout=10, flush_timeout=0.05)
    started, release, completed = threading.Event(), threading.Event(), threading.Event()
    client = ContactClient()
    original = client.update_contact_attributes

    def blocked(**kwargs):
        started.set()
        release.wait(2)
        original(**kwargs)
        completed.set()

    client.update_contact_attributes = blocked
    s.store = ContactStore(client, s.contact, s.contact_policy)
    socket_closed = asyncio.Event()

    async def disconnect():
        return

    async def wait_for_agent():
        await asyncio.Event().wait()

    async def close_socket():
        socket_closed.set()

    s.receive_connect = disconnect
    s.receive_agent = wait_for_agent
    s.socket.close = close_socket
    task = asyncio.create_task(s.run())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.wait_for(task, 0.5)
        assert s.failed and s.store.closed and s.store.worker.done()
        assert socket_closed.is_set()
        assert not client.writes
        # Cleanup can stop waiting, but cannot cancel an already-running AWS call.
        release.set()
        assert await asyncio.to_thread(completed.wait, 1)
        assert client.writes[0]["Attributes"]["AgentPersistenceState"] == "disconnected"
    finally:
        release.set()
        await s.store.close()
