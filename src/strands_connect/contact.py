"""Trusted contact scope and bounded, verified contact writes."""

import asyncio
import re
from dataclasses import dataclass, field

SESSION_ATTRIBUTES = frozenset(
    {
        "AgentProvider",
        "AgentSessionId",
        "AgentPersistenceState",
        "AgentToolCue",
        "AgentDisposition",
        "AgentHandoffNote",
    }
)


class PersistenceError(RuntimeError):
    """A requested contact write could not be verified."""


@dataclass(frozen=True)
class ContactPolicy:
    """Explicit allowlist; contact details are an opt-in preview API."""

    allowed_attributes: frozenset[str] = field(default_factory=lambda: SESSION_ATTRIBUTES)
    allow_contact_details: bool = False
    queue_size: int = 16
    max_value_bytes: int = 4096
    flush_timeout: float = 20

    def __post_init__(self):
        object.__setattr__(self, "allowed_attributes", frozenset(self.allowed_attributes))
        if self.queue_size < 1 or self.max_value_bytes < 1 or self.flush_timeout <= 0:
            raise ValueError("Contact policy limits must be positive")


@dataclass(frozen=True)
class ContactContext:
    instance_id: str
    contact_id: str
    initial_contact_id: str
    collaboration_id: str
    runtime_session_id: str

    @classmethod
    async def resolve(cls, client, instance_arn, init, collaboration_id, runtime_session_id):
        if init.get("instanceArn", instance_arn) != instance_arn:
            raise ValueError("Wrong Connect instance")
        match = re.fullmatch(
            re.escape(instance_arn) + r"/contact/([0-9a-f-]{36})", init.get("contactArn", "")
        )
        if not match:
            raise ValueError("Invalid contact ARN")
        contact_id = match[1]
        instance_id = instance_arn.rsplit("/", 1)[1]
        contact = (
            await asyncio.to_thread(client.describe_contact, InstanceId=instance_id, ContactId=contact_id)
        )["Contact"]
        if contact.get("Arn") != init["contactArn"] or contact.get("Id") != contact_id:
            raise ValueError("Contact ownership mismatch")
        if contact.get("Channel") != "VOICE":
            raise ValueError("This endpoint requires a voice contact")
        return cls(
            instance_id,
            contact_id,
            contact.get("InitialContactId") or contact_id,
            collaboration_id,
            runtime_session_id,
        )


class ContactStore:
    """One writer per session; bounded queue, readback and sticky failure state.

    Repeated assignments are idempotent, business tools are not retried here. Supply a
    boto3 client with finite network timeouts and bounded retries. Cancelling a waiter
    does not cancel an accepted write. A timed-out AWS thread can still finish later;
    shutdown marks it unverified rather than promising rollback or exactly-once delivery.
    """

    def __init__(self, client, context: ContactContext, policy: ContactPolicy | None = None):
        self.client, self.context = client, context
        self.policy = policy or ContactPolicy()
        self.queue = asyncio.Queue(maxsize=self.policy.queue_size)
        self.errors = []
        self.cache = {}
        self.closed = False
        self.worker = asyncio.create_task(self._work())

    async def read(self):
        result = await asyncio.to_thread(
            self.client.get_contact_attributes,
            InstanceId=self.context.instance_id,
            InitialContactId=self.context.initial_contact_id,
        )
        self.cache = {
            k: v for k, v in result.get("Attributes", {}).items() if k in self.policy.allowed_attributes
        }
        return dict(self.cache)

    async def update(self, values: dict[str, str]):
        if not values or set(values) - self.policy.allowed_attributes:
            raise ValueError("Unapproved contact attribute")
        if any(
            not isinstance(v, str) or len(v.encode()) > self.policy.max_value_bytes for v in values.values()
        ):
            raise ValueError("Invalid contact attribute value")
        if sum(len(k.encode()) + len(v.encode()) for k, v in values.items()) > 32768:
            raise ValueError("Contact attribute update exceeds 32 KB")
        return await self._submit("attributes", dict(values))

    async def update_details(self, *, name: str | None = None, description: str | None = None):
        if not self.policy.allow_contact_details:
            raise ValueError("Contact detail updates are not enabled")
        values = {k: v for k, v in {"Name": name, "Description": description}.items() if v is not None}
        if not values:
            raise ValueError("At least one contact detail is required")
        for key, value in values.items():
            if not isinstance(value, str) or len(value) > {"Name": 1024, "Description": 4096}[key]:
                raise ValueError("Invalid contact detail")
        return await self._submit("details", values)

    async def _submit(self, kind, values):
        if self.closed:
            raise PersistenceError("Contact store is closed")
        future = asyncio.get_running_loop().create_future()
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        try:
            self.queue.put_nowait((kind, values, future))
        except asyncio.QueueFull as error:
            self.errors.append("queue_full")
            raise PersistenceError("Contact write queue is full") from error
        return await asyncio.shield(future)

    async def _work(self):
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            kind, values, future = item
            try:
                if kind == "attributes":
                    await asyncio.to_thread(
                        self.client.update_contact_attributes,
                        InstanceId=self.context.instance_id,
                        InitialContactId=self.context.initial_contact_id,
                        Attributes=values,
                    )
                    actual = await self.read()
                else:
                    # UpdateContact operates on the current contact, unlike attributes.
                    await asyncio.to_thread(
                        self.client.update_contact,
                        InstanceId=self.context.instance_id,
                        ContactId=self.context.contact_id,
                        **values,
                    )
                    actual = (
                        await asyncio.to_thread(
                            self.client.describe_contact,
                            InstanceId=self.context.instance_id,
                            ContactId=self.context.contact_id,
                        )
                    )["Contact"]
                if any(actual.get(k) != v for k, v in values.items()):
                    raise PersistenceError("Contact update readback mismatch")
                future.set_result(dict(values))
            except asyncio.CancelledError:
                self.errors.append("shutdown_incomplete")
                future.set_exception(PersistenceError("Contact write interrupted during shutdown"))
                raise
            except Exception as error:
                reason = type(error).__name__
                self.errors.append(reason)
                future.set_exception(PersistenceError("Contact update failed: " + reason))
            finally:
                self.queue.task_done()

    async def flush(self):
        await asyncio.wait_for(self.queue.join(), self.policy.flush_timeout)
        if self.errors:
            raise PersistenceError("One or more contact writes failed")

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await asyncio.wait_for(self.queue.join(), self.policy.flush_timeout)
        finally:
            # This also handles a full queue when shutdown times out.
            while not self.queue.empty():
                _, _, future = self.queue.get_nowait()
                future.set_exception(PersistenceError("Contact write not drained before shutdown"))
                self.queue.task_done()
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
