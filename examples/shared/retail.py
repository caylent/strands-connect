"""Synthetic business logic shared by every provider example; no Connect API calls here."""

import asyncio
import math

from strands import tool

from strands_connect.contact import SESSION_ATTRIBUTES, ContactPolicy

POLICY = ContactPolicy(allowed_attributes=SESSION_ATTRIBUTES | {"OrderId", "OrderStatus"})
PROMPT = """You are a friendly voice assistant for a fictional retail store.
Keep answers short. You can look up synthetic order 1042. Never invent an order status.
Before a lookup, briefly say you will check, then call lookup_order once and wait for
its result. A quiet waiting sound is supplied by the application; do not describe or
imitate it. Keep listening while the lookup runs. Do not announce success before the
tool returns. An unknown order is not an error; offer to try the demo order 1042.
Never request payment or personal information. All orders and products are fictional.
The application saves order results automatically. If a tool reports a save failure,
explain it and do not claim that the update was saved or repeat a business action.
Use complete_contact only when the caller asks or agrees to end. Use escalate_contact
when the caller asks for human help. Say this example saves handoff notes and returns to
its configured Connect flow; do not promise that a staffed queue is available.
After completion or escalation, give one short closing response.
"""


def order_result(order_id):
    if str(order_id).strip().replace(" ", "") == "1042":
        return {"demo": True, "order_id": "1042", "status": "Shipped", "delivery": "tomorrow"}
    return {"demo": True, "found": False, "message": "Only synthetic order 1042 is available."}


def validate_tool_delay(value):
    """Operator-only demo control; never a model-controlled tool argument."""
    try:
        delay = float(value)
    except (ValueError, TypeError):
        raise ValueError("DEMO_TOOL_DELAY_SECONDS must be a finite number from 0 to 30") from None
    if isinstance(value, bool) or not math.isfinite(delay) or not 0 <= delay <= 30:
        raise ValueError("DEMO_TOOL_DELAY_SECONDS must be a finite number from 0 to 30")
    return delay


def make_lookup_order(delay_seconds=0):
    delay = validate_tool_delay(delay_seconds)

    @tool
    async def lookup_order(order_id: str) -> dict:
        """Look up a synthetic order.

        Args:
            order_id: The requested demo order number, such as 1042.
        """
        # Yield to voice input/output and cancellation throughout the demonstration.
        # Real business tools should await their API directly, without this delay.
        await asyncio.sleep(delay)
        return order_result(order_id)

    return lookup_order


def order_attributes(result):
    return (
        {"OrderId": result["order_id"], "OrderStatus": result["status"]}
        if isinstance(result, dict) and result.get("order_id")
        else {}
    )


def configure_session(
    socket, *, connect_client, model_factory, instance_arn, provider, demo_tool_delay_seconds=0, **kwargs
):
    from strands_connect import ConnectSession

    lookup_order = make_lookup_order(demo_tool_delay_seconds)
    return ConnectSession(
        socket,
        instance_arn=instance_arn,
        connect_client=connect_client,
        model_factory=model_factory,
        tools_factory=lambda session: [lookup_order],
        system_prompt=PROMPT,
        provider=provider,
        contact_policy=POLICY,
        result_mappers={"lookup_order": order_attributes},
        **kwargs,
    )
