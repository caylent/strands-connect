# Session duration and cleanup

`ConnectSession(max_session_seconds=300)` has a five-minute hard limit. The timer starts when `run()` starts, so initialization counts toward the budget. Customize it when constructing your session. This is an application limit, not a claim about the maximum duration supported by Connect or a model provider.

There is currently **no automatic wrap-up warning, countdown, or graceful-finish prompt**. Normal completion and escalation happen through their contact tools and verified writes. At the hard limit, the session fails; when initialization succeeded and the socket remains usable, it emits a dependency-failure status, then cleans up. Expiry does not synthesize a successful `COMPLETE` or `ESCALATE`. Configure the Connect flow's error path for the desired recovery or human routing. A future wrap-up policy needs its own design and interruption tests.

## Coordinate the independent limits

| Limit | Current default | Where to change it |
|---|---|---|
| Conversation, including initialization | 300 seconds | `ConnectSession.max_session_seconds` |
| Bridge forwarding loop | 310 seconds | Timeout in `examples/shared/bridge.py` |
| AgentCore maximum session lifetime | 600 seconds | `LifecycleConfiguration.MaxLifetime` in `deployment/agentcore.json` |
| AgentCore idle session timeout | 60 seconds | `LifecycleConfiguration.IdleRuntimeSessionTimeout` in the template |
| Individual contact write wait | 20 seconds | `ContactPolicy.write_timeout` |
| Final contact-state write plus store drain | 20 seconds total | `ContactPolicy.flush_timeout` |

Increasing the conversation limit alone does not extend the bridge or hosted runtime. Allow headroom for error reporting and cleanup, and account for provider connection/reconnect limits. The bridge's current ten-second margin does not cover worst-case cleanup; it can close the transport while the runtime is still cleaning up. The idle timeout is a separate runtime setting, not a caller-silence countdown implemented by this adapter.

## What cleanup guarantees

After the receive tasks stop, the adapter stops the provider with a five-second wait, attempts the final contact state, and drains/closes the store. The final contact-state update and drain share one `flush_timeout` deadline. If configured, the archive callback receives a separate `flush_timeout` budget. These are separate stages: the conversation cap does not impose an absolute deadline on all cleanup or process exit.

A timed-out contact write is unverified. It may still complete in an AWS thread after the session closes, and a later SDK completion does not clear the local failure. Use finite SDK network timeouts and bounded retries in addition to the policy deadlines. See [contact persistence semantics](contact-records.md#persistence-semantics).
