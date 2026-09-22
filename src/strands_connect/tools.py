"""Contact-scoped @tool functions: identifiers are never model-selectable arguments."""

import asyncio

from strands import tool

from .contact import SESSION_ATTRIBUTES
from .hooks import LIFECYCLE_TOOLS


def contact_tools(session):
    @tool
    async def get_contact_attributes() -> dict:
        """Read approved user-defined attributes on the current contact."""
        return await session.store.read()

    @tool
    async def update_contact_attributes(attributes: dict[str, str]) -> dict:
        """Save and verify approved custom attributes on the current contact.

        Args:
            attributes: Approved attribute names and string values to save.
        """
        if set(attributes) & SESSION_ATTRIBUTES:
            raise ValueError("Lifecycle attributes are managed by the application")
        return {"saved": await session.store.update(attributes)}

    @tool
    async def update_contact_details(name: str = "", description: str = "") -> dict:
        """Set a nonempty contact name or description, when enabled by the application.

        Args:
            name: Short contact title. Empty means do not update.
            description: Brief contact summary. Empty means do not update.
        """
        return {
            "saved": await session.store.update_details(
                name=name or None,
                description=description or None,
            )
        }

    async def finish(kind, note):
        if kind not in session.supported:
            raise ValueError("Connect did not advertise this finish type")
        async with asyncio.timeout(session.contact_policy.flush_timeout):
            while any(t["name"] not in LIFECYCLE_TOOLS for t in session.pending_tools.values()):
                await asyncio.sleep(0.02)
        await session.store.flush()
        await session.store.update(
            {
                "AgentDisposition": "escalated" if kind == "ESCALATE" else "completed",
                "AgentHandoffNote": note[:500],
            }
        )
        await session.store.flush()
        session.finish = {"type": kind, "reason": note[:500]}
        return {"saved_to_contact": True, "message": "Give a brief closing response now."}

    @tool
    async def complete_contact(note: str) -> dict:
        """Save a disposition and finish only when the caller requests or agrees to end.

        Args:
            note: Brief factual outcome of the conversation.
        """
        return await finish("COMPLETE", note)

    @tool
    async def escalate_contact(note: str) -> dict:
        """Save handoff context and return ESCALATE to the configured Connect flow.

        Args:
            note: Brief factual handoff summary. The flow controls any human routing.
        """
        return await finish("ESCALATE", note)

    tools = [get_contact_attributes, update_contact_attributes, complete_contact, escalate_contact]
    if session.contact_policy.allow_contact_details:
        tools.append(update_contact_details)
    return tools
