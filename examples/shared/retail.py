"""Synthetic business logic shared by every provider example; no Connect API calls here."""

from strands import tool

from strands_connect.contact import SESSION_ATTRIBUTES, ContactPolicy

POLICY = ContactPolicy(allowed_attributes=SESSION_ATTRIBUTES | {"OrderId", "OrderStatus"})
PROMPT = """You are a friendly voice assistant for a fictional retail store.
Keep answers short. You can look up synthetic order 1042. Never invent an order status.
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


@tool
async def lookup_order(order_id: str) -> dict:
    """Look up a synthetic order.

    Args:
        order_id: The requested demo order number, such as 1042.
    """
    return order_result(order_id)


def order_attributes(result):
    return (
        {"OrderId": result["order_id"], "OrderStatus": result["status"]}
        if isinstance(result, dict) and result.get("order_id")
        else {}
    )


def configure_session(socket, *, connect_client, model_factory, instance_arn, provider, **kwargs):
    from strands_connect import ConnectSession

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
