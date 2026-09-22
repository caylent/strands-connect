from types import SimpleNamespace

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent

from strands_connect import ConnectContactHooks, ContactContext, ContactStore
from tests.fakes import ContactClient


def make_session(client):
    store = ContactStore(client, ContactContext("i", "c", "c", "s", "r"))
    return SimpleNamespace(
        finishing_tool_id=None,
        pending_tools={},
        completed_tools=[],
        cue_enabled=False,
        cue_task=None,
        failed=False,
        finish=None,
        store=store,
        ensure_turn=lambda: {"task_id": "t"},
    )


async def test_save_failure_changes_tool_result_before_model_receives_it():
    s = make_session(ContactClient(fail=True))
    hooks = ConnectContactHooks(s, {"lookup": lambda result: {"AgentDisposition": "checked"}})
    call = {"toolUseId": "id", "name": "lookup", "input": {}}
    await hooks.before_tool(
        BeforeToolCallEvent(agent=None, selected_tool=None, tool_use=call, invocation_state={})
    )
    after = AfterToolCallEvent(
        agent=None,
        selected_tool=None,
        tool_use=call,
        invocation_state={},
        result={"toolUseId": "id", "status": "success", "content": [{"json": {"status": "Shipped"}}]},
    )
    await hooks.after_tool(after)
    assert after.result["status"] == "error"
    assert s.failed and not s.pending_tools
    assert s.completed_tools[0]["status"] == "error"
    await s.store.close()


async def test_failed_business_result_is_not_persisted():
    s = make_session(ContactClient())
    hooks = ConnectContactHooks(s, {"lookup": lambda result: {"AgentDisposition": "checked"}})
    call = {"toolUseId": "id", "name": "lookup", "input": {}}
    await hooks.before_tool(
        BeforeToolCallEvent(agent=None, selected_tool=None, tool_use=call, invocation_state={})
    )
    await hooks.after_tool(
        AfterToolCallEvent(
            agent=None,
            selected_tool=None,
            tool_use=call,
            invocation_state={},
            result={"toolUseId": "id", "status": "error", "content": [{"text": "No order"}]},
        )
    )
    assert s.store.client.writes == []
    assert s.completed_tools[0]["status"] == "error"
    await s.store.close()


async def test_model_tool_cannot_overwrite_lifecycle_state():
    import pytest

    from strands_connect import ContactPolicy, contact_tools

    s = make_session(ContactClient())
    s.contact_policy = ContactPolicy()
    tools = {t.tool_name: t for t in contact_tools(s)}
    assert "update_contact_details" not in tools
    with pytest.raises(ValueError, match="Lifecycle"):
        await tools["update_contact_attributes"](attributes={"AgentPersistenceState": "complete"})
    assert s.store.client.writes == []
    await s.store.close()
