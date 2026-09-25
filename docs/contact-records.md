# Contact records, CTR, and updates

A contact record (historically CTR) is produced by Connect. This package changes supported contact fields and emits associated history; it cannot arbitrarily edit generated queue metrics, recordings, or past exported CTR objects.

| Capability | Mechanism | Scope / verification |
|---|---|---|
| Custom string attributes | `UpdateContactAttributes`, `GetContactAttributes` | Initial contact ID; every queued write is read back |
| Contact title and description | `UpdateContact`, `DescribeContact` | Current contact ID; explicitly opt in; preview API |
| Completion / escalation | Attribute updates + A2A `FINISH` | Only advertised finish types; handoff notes saved before handback |
| Transcript and tool history | A2A `TRACING_SPAN` with OTLP/JSON | Per turn, before terminal status; only when Connect subscribes |
| Audio recordings | Connect recording/storage configuration | Outside the library; validate actual recording playback |
| Exported CTR consumption | Your existing Connect data streaming pipeline | Future integration; not implemented |

## Policy and tools

`ContactPolicy.allowed_attributes` is an explicit set of custom attribute names. Include `SESSION_ATTRIBUTES` when creating `ConnectSession`; these reserved `Agent*` fields record lifecycle state. The model-facing update tool cannot overwrite reserved lifecycle attributes. Application result mappers and lifecycle tools own them.

The optional `update_contact_details` tool is registered only when `allow_contact_details=True`. Its name/description writes use the current contact, whereas custom attributes use the initial contact. Routing, customer endpoints, agent identities, and arbitrary segment attributes are deliberately outside the exposed tool surface.

No tool accepts an instance ID, contact ID, or initial contact ID. `ContactContext.resolve` validates the contact ARN against the configured instance and `DescribeContact` before opening a provider connection. Authenticate ingress; this check does not replace authentication of the caller presenting that context.

## Persistence semantics

The bounded writer queue serializes updates for one session. Async hooks await a write and API readback before returning the business result to the provider. AWS calls run outside the event loop with configured finite timeouts/retries. Failure is sticky: `flush()` fails after any unverified write. Completion waits for pending business tools and drains writes before `FINISH`.

Assignments can be retried by the AWS SDK; business actions are not automatically retried. Two independent sessions for the same initial contact still need application-level coordination. Other writers can overwrite attributes after readback. Cancelling a waiter leaves an accepted write queued; shutdown times out explicitly. A running AWS thread may complete after a timeout. There is no rollback or exactly-once guarantee.

`ContactPolicy.write_timeout` defaults to **20 seconds** and bounds each attribute or contact-detail write's caller wait, including time in the queue, the AWS update, and readback. Expiry raises `PersistenceError` and records a sticky failure even if a later readback succeeds. The accepted write stays on the same worker, preserving ordering; the library does not retry it or start a replacement worker.

`ContactPolicy.flush_timeout` defaults to **20 seconds**. It bounds a flush or close. During session shutdown, the final lifecycle-state write and store drain share a single budget of this length; the final write also retains its per-write limit. `close(timeout=...)` can shorten the drain budget but cannot extend the policy limit. On drain expiry, queued writes are rejected and the worker is cancelled. An already-running AWS call can still complete after closure, including a late lifecycle-state update. An unsuccessful cleanup marks the session failed locally; it cannot promise that an `incomplete` attribute was saved remotely.

These deadlines bound asynchronous waits, not AWS execution or Python thread shutdown. Continue configuring finite SDK connection/read timeouts and retries: a blocked SDK thread can outlive the session and delay process exit. Both policy timeouts must be finite and positive. See [session limits](session-lifecycle.md) for the separate conversation, bridge, and runtime limits.

`AgentPersistenceState=complete` concerns contact updates. It does not assert that Connect has indexed every trace or that a recording exists. To retain an independent application audit, pass an async `archive(record)` callback to `ConnectSession`; secure its storage and retention separately.

## History and data handling

Prior A2A text history can seed the Strands conversation. Model thought text is excluded from the Gemini spoken transcript. Interrupted output is marked as potentially partially played, not acknowledged playback. Tool arguments and results appear in traces; keep them free of credentials and unnecessary personal data. Applications should redact sensitive tool output before returning it or customize the exporter before production use.

## References

- [UpdateContactAttributes](https://docs.aws.amazon.com/connect/latest/APIReference/API_UpdateContactAttributes.html)
- [GetContactAttributes](https://docs.aws.amazon.com/connect/latest/APIReference/API_GetContactAttributes.html)
- [UpdateContact](https://docs.aws.amazon.com/connect/latest/APIReference/API_UpdateContact.html)
- [Connect A2A protocol and tracing](https://docs.aws.amazon.com/connect/latest/devguide/a2a-developer-guide.html)
- [Contact details AI-agent traces](https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-traces.html)
