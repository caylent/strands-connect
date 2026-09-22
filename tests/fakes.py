import asyncio
import base64
import json
import uuid

from strands.experimental.bidi.models.model import BidiModel
from strands.experimental.bidi.types.events import (
    BidiAudioStreamEvent,
    BidiConnectionStartEvent,
    BidiResponseCompleteEvent,
    BidiResponseStartEvent,
    BidiTranscriptCompleteEvent,
)
from strands.types._events import ToolUseStreamEvent

INSTANCE = "arn:aws:connect:us-east-1:123456789012:instance/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONTACT = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class ContactClient:
    def __init__(self, fail=False, mismatch=False):
        self.attributes, self.details, self.writes = {}, {}, []
        self.fail, self.mismatch = fail, mismatch

    def describe_contact(self, InstanceId, ContactId):
        return {
            "Contact": {
                "Id": ContactId,
                "Arn": INSTANCE + "/contact/" + ContactId,
                "InitialContactId": ContactId,
                "Channel": "VOICE",
                **self.details.get(ContactId, {}),
            }
        }

    def update_contact_attributes(self, **kwargs):
        if self.fail:
            raise RuntimeError("Simulated denied write")
        self.writes.append(kwargs)
        if not self.mismatch:
            self.attributes.setdefault(kwargs["InitialContactId"], {}).update(kwargs["Attributes"])

    def get_contact_attributes(self, InitialContactId, **kwargs):
        return {"Attributes": self.attributes.get(InitialContactId, {}).copy()}

    def update_contact(self, InstanceId, ContactId, **kwargs):
        self.writes.append({"InstanceId": InstanceId, "ContactId": ContactId, **kwargs})
        self.details.setdefault(ContactId, {}).update(kwargs)


class ScriptedModel(BidiModel):
    """Real BidiAgent and hooks; only provider network and AWS are simulated."""

    def __init__(self, client, contact=CONTACT, rate=16000):
        self.client, self.contact, self.rate = client, contact, rate
        self.events, self.calls, self.inputs = asyncio.Queue(), {}, []
        self.started = self.stopped = False

    def get_config(self):
        return {"model_id": "scripted-test"}

    def update_config(self, **kwargs):
        pass

    def get_audio_config(self):
        return {
            direction: {"sample_rate": rate, "channels": 1, "format": "pcm"}
            for direction, rate in (("input", self.rate), ("output", 24000))
        }

    async def start(self, system_prompt=None, tools=None, messages=None, **kwargs):
        self.started = True
        self.tool_specs, self.messages = tools, messages
        await self.events.put(BidiConnectionStartEvent(connection_id="test", model="scripted-test"))

    async def stop(self):
        self.stopped = True

    async def request_tool(self, name, arguments):
        key = uuid.uuid4().hex
        self.calls[key] = name
        await self.events.put(BidiResponseStartEvent(response_id=key))
        await self.events.put(ToolUseStreamEvent({}, {"toolUseId": key, "name": name, "input": arguments}))

    async def send(self, content):
        self.inputs.append(content)
        if content["type"] == "bidi_audio_input":
            assert content["sample_rate"] == self.rate
            await self.request_tool("lookup_order", {"order_id": "1042"})
        elif content["type"] == "bidi_text_input" and content["text"] in ("goodbye", "human"):
            name = "complete_contact" if content["text"] == "goodbye" else "escalate_contact"
            await self.request_tool(name, {"note": "Caller requested this outcome."})
        elif content["type"] == "tool_result":
            result = content["tool_result"]
            assert result["status"] == "success", result
            name = self.calls[result["toolUseId"]]
            actual = self.client.attributes[self.contact]
            if name == "lookup_order":
                # This assertion proves the hook persists BEFORE the provider sees the result.
                assert actual["OrderStatus"] == "Shipped"
                text = "Your order has shipped."
            else:
                assert actual["AgentDisposition"] == (
                    "completed" if name == "complete_contact" else "escalated"
                )
                text = "Goodbye."
            await self.events.put(BidiTranscriptCompleteEvent(text, "assistant"))
            await self.events.put(
                BidiAudioStreamEvent(
                    audio=base64.b64encode(b"\x01\x00" * 240).decode(),
                    sample_rate=24000,
                    format="pcm",
                    channels=1,
                )
            )
            await self.events.put(BidiResponseCompleteEvent(response_id="response", stop_reason="complete"))

    async def receive(self):
        while True:
            yield await self.events.get()


class MemorySocket:
    headers = {}

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.frames = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.incoming.get()
        if item is None:
            raise StopAsyncIteration
        return json.dumps(item)

    async def send(self, payload):
        frame = json.loads(payload)
        self.frames.append(frame)
        await self.outgoing.put(frame)

    async def close(self):
        self.closed = True
