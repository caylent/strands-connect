"""Connect A2A voice extensions around a Strands BidiAgent, independent of its model provider."""

import asyncio
import base64
import contextlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from strands.experimental.bidi import BidiAgent

from .audio import chunks, fade_in, soft_pulse
from .contact import SESSION_ATTRIBUTES, ContactContext, ContactPolicy, ContactStore
from .hooks import ConnectContactHooks
from .tools import contact_tools

EXT = "https://docs.aws.amazon.com/connect/a2a/ext/v1"
LOG = logging.getLogger(__name__)


def uid():
    return uuid.uuid4().hex


def event(name, **fields):
    LOG.info(json.dumps({"event": name, **fields}))


def attrs(values):
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in values.items()]


def pcm_config(rate):
    return {"encoding": "LINEAR_PCM", "sampleRateHertz": rate, "sampleSizeBits": 16, "channelCount": 1}


def message(kind, data, context):
    return {
        "messageId": uid(),
        "contextId": context,
        "role": "ROLE_AGENT",
        "parts": [{"data": data, "mediaType": "application/json"}],
        "extensions": [EXT],
        "metadata": {EXT + "/eventType": kind},
    }


def history_messages(history):
    """Seed prior A2A text turns; binary and arbitrary data parts are not instructions."""
    if not isinstance(history, list) or len(history) > 100:
        raise ValueError("Conversation history exceeds the supported budget")
    messages = []
    for item in history:
        role = {"ROLE_USER": "user", "ROLE_AGENT": "assistant"}.get(item.get("role"))
        text = "\n".join(p["text"] for p in item.get("parts", []) if isinstance(p.get("text"), str))
        if len(text) > 8000:
            raise ValueError("History turn exceeds the supported budget")
        if role and text:
            messages.append({"role": role, "content": [{"text": text}]})
    return messages


class ConnectSession:
    def __init__(
        self,
        socket,
        *,
        instance_arn,
        connect_client,
        model_factory,
        tools_factory=None,
        system_prompt,
        provider="custom",
        contact_policy=None,
        result_mappers=None,
        greeting="Please greet the caller and offer help.",
        agent_name="connect-agent",
        max_session_seconds=300,
        runtime_session_id=None,
        cue_enabled=True,
        archive=None,
    ):
        self.socket, self.instance_arn, self.connect_client = socket, instance_arn, connect_client
        self.model_factory, self.tools_factory, self.system_prompt = (
            model_factory,
            tools_factory,
            system_prompt,
        )
        self.provider, self.runtime_session_id = provider, runtime_session_id or str(uuid.uuid4())
        self.cue_enabled, self.archive = cue_enabled, archive
        self.contact_policy = contact_policy or ContactPolicy()
        if not SESSION_ATTRIBUTES <= self.contact_policy.allowed_attributes:
            raise ValueError("Contact policy must include SESSION_ATTRIBUTES")
        self.result_mappers = dict(result_mappers or {})
        self.greeting, self.agent_name = greeting, agent_name
        if max_session_seconds <= 0:
            raise ValueError("Session duration must be positive")
        self.max_session_seconds = max_session_seconds
        self.finishing_tool_id = None
        self.finished_sent = False
        self.subscribe_to_traces = False
        self.last_request_id = None
        self.context = None
        self.contact = None
        self.store = None
        self.agent = None
        self.model_id = None
        self.input_rate, self.output_rate = 16000, 24000
        self.supported = []
        self.ready, self.initialized = asyncio.Event(), asyncio.Event()
        self.send_lock, self.audio_lock = asyncio.Lock(), asyncio.Lock()
        self.fragments = {}
        self.turn = None
        self.turn_number = 0
        self.pending_tools = {}
        self.completed_tools = []
        self.history = []
        self.finish = None
        self.failed = False
        self.cue_task = None
        self.last_model_audio = 0
        self.audio_generation = 0
        self.input_bytes = self.output_bytes = 0
        self.upstream_trace = socket.headers.get("traceparent", "")

    def ensure_turn(self):
        if self.turn is None:
            self.turn_number += 1
            self.turn = {
                "task_id": uid(),
                "audio_id": uid(),
                "audio_started": False,
                "started": time.time_ns(),
                "input": "",
                "output": "",
                "interrupted": False,
                "number": self.turn_number,
                "events": [],
            }
        return self.turn

    async def send(self, result, request_id=None):
        frame = {"jsonrpc": "2.0", "id": request_id or uid(), "result": result}
        payload = json.dumps(frame, separators=(",", ":"))
        frames = [payload]
        if len(payload.encode()) > 24000:
            encoded = base64.b64encode(payload.encode()).decode()
            parts = [encoded[i : i + 16000] for i in range(0, len(encoded), 16000)]
            if len(parts) > 64:
                raise ValueError("Outbound trace exceeds fragment budget")
            fragment_id = uid()
            frames = [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": frame["id"],
                        "result": {
                            "message": message(
                                "FRAGMENT",
                                {
                                    "fragment": {
                                        "fragmentId": fragment_id,
                                        "partNumber": i,
                                        "totalParts": len(parts),
                                        "payload": p,
                                        "encoding": "base64",
                                    }
                                },
                                self.context,
                            )
                        },
                    }
                )
                for i, p in enumerate(parts)
            ]
        async with asyncio.timeout(8):
            async with self.send_lock:
                for payload in frames:
                    await self.socket.send(payload)

    async def artifact(self, kind, parts, *, audio=False, last=True, source=None):
        turn = self.ensure_turn()
        metadata = {EXT + "/eventType": kind}
        if source:
            metadata["strands.connect/audioSource"] = source
        await self.send(
            {
                "artifactUpdate": {
                    "taskId": turn["task_id"],
                    "contextId": self.context,
                    "artifact": {
                        "artifactId": turn["audio_id"] if audio else uid(),
                        "parts": parts,
                        "metadata": metadata,
                    },
                    "append": turn["audio_started"] if audio else False,
                    "lastChunk": last,
                }
            }
        )
        if audio:
            turn["audio_started"] = True

    async def output_audio(self, pcm, source="model", generation=None):
        await self.ready.wait()
        async with self.audio_lock:
            if generation is not None and generation != self.audio_generation:
                return
            for offset in range(0, len(pcm), 12000):
                part = pcm[offset : offset + 12000]
                await self.artifact(
                    "AUDIO_RESPONSE_CHUNK",
                    [{"raw": base64.b64encode(part).decode(), "mediaType": "audio/lpcm"}],
                    audio=True,
                    last=False,
                    source=source,
                )
                self.output_bytes += len(part)

    async def stop_cue(self):
        task, self.cue_task = self.cue_task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def cue_loop(self):
        generation = self.audio_generation
        try:
            await self.ready.wait()
            # Delay only the cue, never the tool. Quick calls should stay silent.
            await asyncio.sleep(0.7)
            while time.monotonic() - self.last_model_audio < 0.15:
                await asyncio.sleep(0.03)
            if not self.pending_tools or generation != self.audio_generation:
                return
            loop = await asyncio.to_thread(soft_pulse, self.output_rate)
            played = 0
            while self.pending_tools and generation == self.audio_generation:
                event("tool_cue", context=self.context)
                for pcm in chunks(loop, self.output_rate):
                    if not self.pending_tools or generation != self.audio_generation:
                        return
                    await self.output_audio(fade_in(pcm, self.output_rate, played), "tool_cue", generation)
                    played += len(pcm) // 2
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            raise
        finally:
            if self.cue_task is asyncio.current_task():
                self.cue_task = None

    def span_message(self, role, participant, text, kind="TEXT_MESSAGE", timestamp=None):
        return {
            "name": "aws.connect.span.message",
            "timeUnixNano": str(timestamp or time.time_ns()),
            "attributes": attrs(
                {
                    "aws.connect.span.message.role": role,
                    "aws.connect.span.message.participant": participant,
                    "aws.connect.span.message.type": kind,
                    "aws.connect.span.message.content": text,
                }
            ),
        }

    async def finish_turn(self, *, interrupted=False, error=False):
        if self.turn is None:
            return
        await self.stop_cue()
        turn = self.turn
        turn["interrupted"] = interrupted
        now = time.time_ns()
        if turn["audio_started"] and not interrupted:
            await self.artifact(
                "AUDIO_RESPONSE_CHUNK", [{"raw": "", "mediaType": "audio/lpcm"}], audio=True, last=True
            )
        completed, self.completed_tools = self.completed_tools, []
        records = completed + [dict(t, ended=now, status="pending") for t in self.pending_tools.values()]
        trace_id, root_id = uid(), uid()[:16]
        trace_parent = None
        if re.fullmatch(r"[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", self.upstream_trace):
            trace_parent = self.upstream_trace.split("-")
            if turn["number"] == 1:
                trace_id = trace_parent[1]
        transcript_events = [
            self.span_message("input", "user", turn["input"] or "[session start]"),
            self.span_message("output", "assistant", turn["output"] or "[no spoken response]"),
        ]
        common = {
            "traceId": trace_id,
            "startTimeUnixNano": str(turn["started"]),
            "endTimeUnixNano": str(now),
            "status": {"code": 2 if error else 1},
        }
        root = dict(
            common,
            spanId=root_id,
            name="invoke_agent " + self.agent_name,
            kind=2,
            attributes=attrs(
                {
                    "gen_ai.agent.name": self.agent_name,
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.request.model": self.model_id,
                    "aws.connect.contact.id": self.contact.contact_id,
                    "strands.connect.runtime.session_id": self.runtime_session_id,
                    "strands.connect.audio.interrupted": interrupted,
                    "strands.connect.audio.playback_acknowledged": False,
                }
            ),
            events=transcript_events,
        )
        if trace_parent:
            if turn["number"] == 1:
                root["parentSpanId"] = trace_parent[2]
            else:
                root["links"] = [{"traceId": trace_parent[1], "spanId": trace_parent[2]}]
        if interrupted:
            root["events"].append(
                {
                    "name": "strands.connect.audio.interrupted",
                    "timeUnixNano": str(now),
                    "attributes": attrs({"reason": "caller speech", "playback": "may be partial"}),
                }
            )
        spans = [
            root,
            dict(
                common,
                spanId=uid()[:16],
                parentSpanId=root_id,
                name="chat " + self.model_id,
                kind=3,
                attributes=attrs({"gen_ai.operation.name": "chat", "gen_ai.request.model": self.model_id}),
                events=transcript_events,
            ),
        ]
        for tool in records:
            spans.append(
                {
                    "traceId": trace_id,
                    "spanId": tool["id"][:16],
                    "parentSpanId": root_id,
                    "name": "execute_tool " + tool["name"],
                    "kind": 3,
                    "startTimeUnixNano": str(tool["started"]),
                    "endTimeUnixNano": str(tool["ended"]),
                    "attributes": attrs(
                        {
                            "gen_ai.operation.name": "execute_tool",
                            "gen_ai.tool.name": tool["name"],
                            "strands.connect.tool.status": tool.get("status", "cancelled"),
                            "strands.connect.tool.initiated_task": tool["initiated_task"],
                        }
                    ),
                    "events": [
                        self.span_message("input", "assistant", json.dumps(tool["arguments"]), "TOOL_CALL"),
                        self.span_message(
                            "output",
                            "tool",
                            json.dumps(tool.get("result", {"status": "pending"})),
                            "TOOL_RESULT",
                        ),
                    ],
                    "status": {"code": 2 if tool.get("status") == "error" else 1},
                }
            )
        otlp = {
            "resourceSpans": [
                {
                    "resource": {"attributes": attrs({"service.name": "strands-connect"})},
                    "scopeSpans": [
                        {"scope": {"name": "amazon.connect.ai-agent", "version": "1.0.0"}, "spans": spans}
                    ],
                }
            ]
        }
        if self.subscribe_to_traces:
            await self.artifact(
                "TRACING_SPAN", [{"data": {"tracingSpan": {"otlp": otlp}}, "mediaType": "application/json"}]
            )
        status = {
            "state": "TASK_STATE_FAILED" if error else "TASK_STATE_COMPLETED",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if self.finish and not interrupted and not error:
            status["message"] = message("FINISH", {"finish": self.finish}, self.context)
        elif error:
            status["message"] = message(
                "ERROR",
                {
                    "error": {
                        "errorCode": 424,
                        "errorCategory": "DEPENDENCY_FAILURE",
                        "errorReason": "The voice session could not finish reliably.",
                    }
                },
                self.context,
            )
        await self.send(
            {"statusUpdate": {"taskId": turn["task_id"], "contextId": self.context, "status": status}}
        )
        if self.finish and not interrupted and not error:
            self.finished_sent = True
        self.history.append(dict(turn, ended=now, tools=records, error=error))
        self.turn = None
        event(
            "turn_complete",
            context=self.context,
            task=turn["task_id"],
            interrupted=interrupted,
            error=error,
            finish=self.finish,
            input_chars=len(turn["input"]),
            output_chars=len(turn["output"]),
        )

    async def initialize(self, frame, incoming, init):
        if self.context is not None:
            raise ValueError("Duplicate initialization")
        if "audioInputConfiguration" not in init:
            raise ValueError("Native voice input required")
        self.contact = await ContactContext.resolve(
            self.connect_client, self.instance_arn, init, incoming["contextId"], self.runtime_session_id
        )
        self.context = incoming["contextId"]
        self.supported = init.get("supportedFinishTypes", [])
        self.subscribe_to_traces = init.get("subscribeToTracingEvents") is True
        self.store = ContactStore(self.connect_client, self.contact, self.contact_policy)
        await self.store.update(
            {
                "AgentProvider": self.provider,
                "AgentSessionId": self.runtime_session_id,
                "AgentPersistenceState": "active",
                "AgentToolCue": "enabled" if self.cue_enabled else "disabled",
            }
        )
        model = self.model_factory()
        config = model.get_audio_config()
        self.input_rate = config["input"]["sample_rate"]
        self.output_rate = config["output"]["sample_rate"]
        self.model_id = model.get_config()["model_id"]
        if self.input_rate not in (8000, 16000, 24000) or self.output_rate not in (8000, 16000, 24000):
            raise ValueError("Unsupported negotiated PCM rate")
        if any(
            config[d].get("format") != "pcm" or config[d].get("channels") != 1 for d in ("input", "output")
        ):
            raise ValueError("Connect requires mono PCM audio")
        self.agent = BidiAgent(
            model=model,
            system_prompt=self.system_prompt,
            tools=contact_tools(self) + (self.tools_factory(self) if self.tools_factory else []),
            hooks=[ConnectContactHooks(self, self.result_mappers)],
            messages=history_messages(init.get("history", [])),
            name=self.agent_name,
            agent_id="strands-connect",
        )
        await asyncio.wait_for(self.agent.start(), 25)
        await self.send(
            {
                "message": message(
                    "INIT_SESSION_RESPONSE",
                    {
                        "initSessionResponse": {
                            "statusCode": "200",
                            "audioInputConfiguration": pcm_config(self.input_rate),
                            "audioOutputConfiguration": pcm_config(self.output_rate),
                        }
                    },
                    self.context,
                )
            },
            frame["id"],
        )
        self.initialized.set()
        event(
            "session_initialized",
            context=self.context,
            contact=self.contact.contact_id,
            initial_contact=self.contact.initial_contact_id,
            runtime_session=self.runtime_session_id,
            provider=self.provider,
            model=self.model_id,
        )

    async def receive_connect(self):
        async for raw in self.socket:
            frame = json.loads(raw)
            self.last_request_id = frame.get("id")
            incoming = frame.get("params", {}).get("message")
            if frame.get("method") not in ("SendMessage", "message/send", "message/stream") or not incoming:
                raise ValueError("Expected SendMessage")
            kind = incoming.get("metadata", {}).get(EXT + "/eventType")
            if kind == "FRAGMENT":
                f = incoming["parts"][0]["data"]["fragment"]
                n, i = f["totalParts"], f["partNumber"]
                if not 0 < n <= 64 or not 0 <= i < n or len(f["payload"]) > 64000:
                    raise ValueError("Invalid fragment")
                if len(self.fragments) >= 8 and f["fragmentId"] not in self.fragments:
                    raise ValueError("Fragment limit")
                parts = self.fragments.setdefault(f["fragmentId"], {"total": n, "parts": {}})
                if parts["total"] != n:
                    raise ValueError("Conflicting fragment totals")
                parts["parts"][i] = f["payload"]
                if sum(len(p) for p in parts["parts"].values()) > 1048576:
                    raise ValueError("Fragment byte limit")
                if len(parts["parts"]) != n:
                    continue
                encoded = "".join(parts["parts"][j] for j in range(n))
                del self.fragments[f["fragmentId"]]
                if len(encoded) > 1048576:
                    raise ValueError("Fragment byte limit")
                frame = json.loads(base64.b64decode(encoded, validate=True))
                incoming = frame["params"]["message"]
                kind = incoming.get("metadata", {}).get(EXT + "/eventType")
            if kind == "INIT_SESSION":
                await self.initialize(frame, incoming, incoming["parts"][0]["data"]["initSession"])
                continue
            if not self.initialized.is_set() or incoming.get("contextId", self.context) != self.context:
                raise ValueError("Uninitialized or mismatched contact context")
            if kind == "CHANNEL_STATE":
                state = incoming["parts"][0]["data"]["channelState"]["state"]
                if state == "READY" and not self.ready.is_set():
                    self.ready.set()
                    await self.agent.send(self.greeting)
                continue
            if kind == "ERROR":
                self.failed = True
                event("connect_protocol_error", context=self.context)
                continue
            if kind == "INTERRUPTION":
                self.audio_generation += 1
                await self.stop_cue()
                continue
            for part in incoming.get("parts", []):
                if "raw" in part:
                    pcm = base64.b64decode(part["raw"], validate=True)
                    if len(pcm) % 2 or len(pcm) > 64000:
                        raise ValueError("Invalid PCM frame")
                    self.input_bytes += len(pcm)
                    await self.agent.send(
                        {
                            "type": "bidi_audio_input",
                            "audio": part["raw"],
                            "format": "pcm",
                            "sample_rate": self.input_rate,
                            "channels": 1,
                        }
                    )
                elif "text" in part:
                    await self.agent.send(part["text"][:8000])
                elif "dtmfInputComplete" in part.get("data", {}):
                    digits = part["data"]["dtmfInputComplete"].get("inputString", "")[:32]
                    await self.agent.send("Caller entered these digits: " + digits)

    async def receive_agent(self):
        await self.initialized.wait()
        async for item in self.agent.receive():
            kind = item.get("type")
            if kind == "bidi_response_start":
                self.ensure_turn()
            elif kind == "bidi_audio_stream":
                await self.stop_cue()
                self.last_model_audio = time.monotonic()
                if (
                    item["sample_rate"] != self.output_rate
                    or item["format"] != "pcm"
                    or item.get("channels", 1) != 1
                ):
                    raise ValueError("Provider changed negotiated audio format")
                await self.output_audio(base64.b64decode(item["audio"]))
            elif kind in ("bidi_transcript_stream", "bidi_transcript_complete"):
                turn = self.ensure_turn()
                role = "input" if item["role"] == "user" else "output"
                if kind == "bidi_transcript_complete":
                    turn[role] = item["transcript"][:20000]
                else:
                    turn[role] = (turn[role] + item["delta"])[:20000]
            elif kind == "bidi_interruption":
                self.audio_generation += 1
                await self.stop_cue()
                await self.send(
                    {
                        "message": message(
                            "INTERRUPTION",
                            {
                                "interruption": {
                                    "type": "USER_AUDIO_INPUT",
                                    "reason": "Strands detected caller speech",
                                }
                            },
                            self.context,
                        )
                    }
                )
                await self.finish_turn(interrupted=True)
                event("caller_interruption", context=self.context)
            elif kind == "bidi_response_complete":
                reason = item.get("stop_reason")
                if reason == "tool_use":
                    continue
                if self.finish and reason not in ("interrupted", "error"):
                    await self.store.flush()
                    await self.store.update(
                        {"AgentPersistenceState": "incomplete" if self.failed else "complete"}
                    )
                    await self.store.flush()
                if reason == "error":
                    self.failed = True
                    self.finish = None
                await self.finish_turn(interrupted=reason == "interrupted", error=reason == "error")
                if self.finished_sent:
                    return
            elif kind == "bidi_connection_close":
                if not self.finished_sent:
                    raise RuntimeError("Provider connection closed before completion")
                return

    async def run(self):
        tasks = [asyncio.create_task(self.receive_connect()), asyncio.create_task(self.receive_agent())]
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=self.max_session_seconds, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                raise TimeoutError("Voice session time limit")
            for task in done:
                task.result()
        except Exception as error:
            self.failed = True
            event(
                "session_error",
                context=self.context,
                error_type=type(error).__name__,
            )
            if not self.initialized.is_set():
                with contextlib.suppress(Exception):
                    await self.socket.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": self.last_request_id,
                                "error": {"code": -32603, "message": "Voice session initialization failed"},
                            }
                        )
                    )
            elif self.context and self.model_id and not self.finished_sent:
                with contextlib.suppress(Exception):
                    self.ensure_turn()
                    self.finish = None
                    await self.finish_turn(error=True)
        finally:
            await self.stop_cue()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.agent:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.agent.stop(), 5)
            if self.store:
                cleanup_deadline = asyncio.get_running_loop().time() + self.contact_policy.flush_timeout
                try:
                    async with asyncio.timeout_at(cleanup_deadline):
                        if not self.finished_sent or self.failed:
                            await self.store.update(
                                {"AgentPersistenceState": "incomplete" if self.failed else "disconnected"}
                            )
                except Exception:
                    self.failed = True
                    event("final_persistence_error", context=self.context)
                finally:
                    try:
                        await self.store.close(
                            timeout=max(0, cleanup_deadline - asyncio.get_running_loop().time())
                        )
                    except Exception:
                        self.failed = True
                        event("contact_store_close_error", context=self.context)
            if self.contact and self.archive:
                try:
                    await asyncio.wait_for(
                        self.archive(
                            {
                                "contact": self.contact.__dict__,
                                "provider": self.provider,
                                "model": self.model_id,
                                "turns": self.history,
                                "unfinished_turn": self.turn,
                                "pending_tools": list(self.pending_tools.values()),
                                "finish": self.finish,
                                "failed": self.failed,
                                "input_bytes": self.input_bytes,
                                "output_bytes": self.output_bytes,
                            }
                        ),
                        timeout=self.contact_policy.flush_timeout,
                    )
                except Exception:
                    self.failed = True
                    event("audit_persistence_error", context=self.context)
            await self.socket.close()
            event(
                "session_closed",
                context=self.context,
                runtime_session=self.runtime_session_id,
                failed=self.failed,
                input_bytes=self.input_bytes,
                output_bytes=self.output_bytes,
            )
