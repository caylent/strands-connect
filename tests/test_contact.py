import asyncio
import threading

import pytest

from strands_connect import ContactContext, ContactPolicy, ContactStore, PersistenceError
from tests.fakes import CONTACT, INSTANCE, ContactClient


def context(contact="current", initial="initial"):
    return ContactContext("instance", contact, initial, "collaboration", "runtime")


def policy(**kwargs):
    return ContactPolicy(allowed_attributes={"OrderId", "OrderStatus"}, **kwargs)


async def test_resolve_validates_contact_and_uses_initial_leg():
    client = ContactClient()
    client.details[CONTACT] = {"InitialContactId": "initial-leg"}
    ctx = await ContactContext.resolve(
        client, INSTANCE, {"contactArn": INSTANCE + "/contact/" + CONTACT}, "s", "r"
    )
    assert ctx.initial_contact_id == "initial-leg"
    with pytest.raises(ValueError, match="Invalid contact"):
        await ContactContext.resolve(client, INSTANCE, {"contactArn": "arn:foreign"}, "s", "r")
    client.details[CONTACT]["Channel"] = "CHAT"
    with pytest.raises(ValueError, match="voice"):
        await ContactContext.resolve(
            client, INSTANCE, {"contactArn": INSTANCE + "/contact/" + CONTACT}, "s", "r"
        )


async def test_concurrent_contacts_and_allowlist():
    client = ContactClient()
    stores = [ContactStore(client, context(initial=i), policy()) for i in ("a", "b")]
    try:
        await asyncio.gather(*(s.update({"OrderId": str(i)}) for i, s in enumerate(stores)))
        assert [await s.read() for s in stores] == [{"OrderId": "0"}, {"OrderId": "1"}]
        with pytest.raises(ValueError, match="Unapproved"):
            await stores[0].update({"InitialContactId": "b"})
    finally:
        await asyncio.gather(*(s.close() for s in stores))


@pytest.mark.parametrize("kwargs", [{"fail": True}, {"mismatch": True}])
async def test_failed_write_and_readback_prevent_successful_flush(kwargs):
    store = ContactStore(ContactClient(**kwargs), context(), policy())
    try:
        with pytest.raises(PersistenceError):
            await store.update({"OrderStatus": "Shipped"})
        with pytest.raises(PersistenceError):
            await store.flush()
    finally:
        await store.close()


async def test_cancelled_waiter_does_not_cancel_accepted_write():
    store = ContactStore(ContactClient(), context(), policy())
    task = asyncio.create_task(store.update({"OrderId": "1042"}))
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await store.flush()
    assert (await store.read())["OrderId"] == "1042"
    await store.close()
    with pytest.raises(PersistenceError, match="closed"):
        await store.update({"OrderId": "1042"})


async def test_details_are_opt_in_and_target_current_leg():
    client = ContactClient()
    store = ContactStore(client, context(), policy(allow_contact_details=True))
    try:
        assert await store.update_details(name="Order question", description="Shipped") == {
            "Name": "Order question",
            "Description": "Shipped",
        }
        assert client.writes[0]["ContactId"] == "current"
        await store.update({"OrderId": "1042"})
        assert client.writes[1]["InitialContactId"] == "initial"
    finally:
        await store.close()
    store = ContactStore(client, context(), policy())
    try:
        with pytest.raises(ValueError, match="not enabled"):
            await store.update_details(name="Denied")
    finally:
        await store.close()


async def test_full_queue_shutdown_releases_waiters_and_worker():
    release = threading.Event()
    client = ContactClient()
    original = client.update_contact_attributes

    def slow(**kwargs):
        release.wait(2)
        original(**kwargs)

    client.update_contact_attributes = slow
    store = ContactStore(client, context(), policy(queue_size=1, flush_timeout=0.03))
    first = asyncio.create_task(store.update({"OrderId": "1"}))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(store.update({"OrderId": "2"}))
    await asyncio.sleep(0)
    with pytest.raises(PersistenceError, match="full"):
        await store.update({"OrderId": "3"})
    try:
        with pytest.raises(TimeoutError):
            await store.close()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert all(isinstance(r, PersistenceError) for r in results)
        assert store.worker.done()
    finally:
        release.set()
