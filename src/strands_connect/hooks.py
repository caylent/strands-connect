"""Public Strands hooks: tool tracing and mandatory persistence before model continuation."""

import asyncio
import json
import time
import uuid

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

LIFECYCLE_TOOLS = frozenset({"complete_contact", "escalate_contact"})


def result_value(result):
    """Decode the ordinary @tool result shape without losing structured JSON."""
    content = result.get("content", [])
    if len(content) == 1:
        if "json" in content[0]:
            return content[0]["json"]
        text = content[0].get("text", "")
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text
    return content


class ConnectContactHooks(HookProvider):
    """Install with BidiAgent(hooks=[...]); create one instance per ConnectSession.

    result_mappers maps a tool name to a synchronous function(result) -> attributes.
    The hook awaits the bounded contact writer before Strands returns that tool result
    to the model. Audio processing stays on separate tasks. No automatic tool retries.
    """

    def __init__(self, session, result_mappers=None):
        self.session = session
        self.result_mappers = dict(result_mappers or {})

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    async def before_tool(self, event: BeforeToolCallEvent) -> None:
        s, call = self.session, event.tool_use
        if s.finishing_tool_id is not None:
            event.cancel_tool = "The contact is finishing; no additional tools may start."
        elif call["name"] in LIFECYCLE_TOOLS:
            s.finishing_tool_id = call["toolUseId"]
        turn = s.ensure_turn()
        s.pending_tools[call["toolUseId"]] = {
            "id": uuid.uuid4().hex,
            "call_id": call["toolUseId"],
            "name": call["name"],
            "arguments": call["input"],
            "started": time.time_ns(),
            "initiated_task": turn["task_id"],
        }
        if not event.cancel_tool and call["name"] not in LIFECYCLE_TOOLS and s.cue_enabled and not s.cue_task:
            s.cue_task = asyncio.create_task(s.cue_loop())

    async def after_tool(self, event: AfterToolCallEvent) -> None:
        s, call = self.session, event.tool_use
        record = s.pending_tools.get(call["toolUseId"])
        if record is None:
            return
        try:
            mapper = self.result_mappers.get(call["name"])
            if event.result.get("status") != "error" and mapper:
                attributes = mapper(result_value(event.result))
                if attributes:
                    await s.store.update(attributes)
            record["result"] = event.result
            record["status"] = "error" if event.result.get("status") == "error" else "ok"
        except Exception:
            s.failed = True
            event.result = {
                "toolUseId": call["toolUseId"],
                "status": "error",
                "content": [
                    {
                        "text": "The tool ran, but its contact update could not be verified. "
                        "Do not claim it was saved or automatically repeat the business action."
                    }
                ],
            }
            record.update(result=event.result, status="error")
        finally:
            if s.store.errors:
                s.failed = True
            record["ended"] = time.time_ns()
            record.setdefault("status", "cancelled")
            s.completed_tools.append(record)
            s.pending_tools.pop(call["toolUseId"], None)
            if call["toolUseId"] == s.finishing_tool_id and not s.finish:
                s.finishing_tool_id = None
