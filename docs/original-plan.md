# Original adapter proposal — public project scope

The original September 21, 2026 proposal was **Reusable Connect adapter for Strands and AgentCore**. This public version preserves its design and acceptance criteria; account-specific prototype deployment details are omitted.

Build a contact-scoped adapter around Strands `BidiAgent`, hosted in Amazon Bedrock AgentCore. An application supplies its model provider, prompt, and business tools. The adapter handles Connect's bidirectional audio protocol, contact context, persistence, transcripts, tool traces, interruptions, and completion/escalation.

## Required responsibilities

1. Negotiate PCM audio; wait for channel readiness; handle bounded buffering, interruptions, errors, and disconnects.
2. Resolve the current and initial contact from authenticated session context and Connect APIs. Keep identifiers out of model-selected tool parameters.
3. Offer scoped attribute read/update helpers. Automatically persist configured business-tool outcomes outside model discretion. Surface write/readback failures; make no exactly-once claim.
4. Send both participants' transcripts and tool requests/results/timings through Connect's A2A trace format. Mark interrupted generated speech as potentially partially played.
5. Drain contact updates and traces before completion or escalation. Persist disposition and handoff notes.
6. Document AgentCore hosting, authentication, collaborator registration, Lex prerequisites, flow setup, logging, recording, and permissions.

Use the direct AgentCore collaborator path if the target account supports native audio there. Otherwise retain a thin authenticated bridge between the Connect external application and AgentCore. A generic A2A server is insufficient: Connect has its own voice extensions.

## Three distinct persistence paths

- Custom contact attributes, available to flows and agents through Connect APIs.
- Transcript and tool history, emitted as A2A traces and indexed by Connect's automated interaction experience.
- Audio recording, configured separately in Connect storage and the contact flow.

AgentCore logs or an application audit file do not establish that Connect Contact details shows the transcript. Generated audio does not prove what the caller heard after interruption.

## Acceptance criteria

- Multiple voice turns through a real Connect contact.
- Interruption without stale queued speech.
- Mapped tool result saved and read by a subsequent flow step.
- Both transcripts, tool calls/results, and timings visible on the correct contact.
- Recording playback when enabled.
- Completion and escalation with handoff notes.
- Explicit incomplete/error outcomes after provider or persistence failures.
- Isolation across simultaneous contacts and runtime sessions.
- A second provider working without contact-persistence changes.

## Implementation status

See [verification](verification.md). The initial reusable library and three provider examples implement the core transport/hooks/tools. Offline contract checks are separate from live provider and Connect acceptance. The original prototype supplied the starting transport; its deployment results are not asserted as verification of every change in this library.
