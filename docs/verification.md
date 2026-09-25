# Verification and limitations

Initial implementation checked September 22, 2026; Python 3.14 / Nova 2 Sonic, bounded-write, soft-pulse, and slow-tool demo updates checked September 25, 2026. This page separates implementation tests from live service acceptance.

## Verified locally

- Behavioral tests run with the real pinned Strands `BidiAgent`, its tool executor, public hooks, and local WebSockets. AWS responses and voice generation are simulated in these acceptance fixtures.
- The 24 kHz OpenAI and 16/24 kHz Gemini/Nova 2 Sonic profiles negotiate audio, execute order lookup, persist mapped results before returning them to the model, emit tool/transcript traces, and finish or escalate with saved notes.
- The **actual official OpenAI Python SDK** connects to a local protocol server; session configuration, audio events, streamed function calls, and connection cleanup are exercised without an external API key.
- AgentCore's actual ASGI application is exercised locally for health, runtime-session context, and first-message handling. The bearer-to-runtime bridge is tested over WebSockets for authentication, A2A headers, correlation, and forwarding.
- Contact ownership and initial/current leg separation, concurrent contact isolation, allowlists, write/readback failures, cancelled waiters, queue saturation, per-write deadlines (including queue time and readback), late AWS completion, and shared final contact-cleanup deadlines are covered.
- Audio readiness, soft-pulse PCM levels and loop seams at all negotiated rates, quick-call silence, continuous looping, prompt cue cancellation on tool completion/interruption, speech pause/resume through estimated queued playback, interruption markers, final trace ordering, frame fragmentation, DTMF completion, and Gemini compatibility behavior are covered.
- A delayed lookup emits multiple cue frames while pending and accepts caller audio before the tool returns, for all three provider audio profiles. A disconnect cancels the asynchronous demo delay before an order result is computed or saved. Invalid delay settings fail at startup; all apps default to eight seconds. These tests use simulated providers/AWS, not live calls.
- The offline HTML/WAV rehearsal preserves every captured PCM sample despite jittered arrival timestamps. Its regression checks both the WAV and the audio embedded in the page; CI captures a fresh two-second rehearsal on Python 3.14. This is a developer preview, not a hosted endpoint or live recording.
- All 82 behavioral tests pass on Python 3.14.3, including Sonic voice selection in the actual provider configuration event. Wheel/source distribution builds pass. The 0.2.0 verification also checked a clean Sonic + AgentCore wheel installation without OpenAI or Gemini packages; the initial implementation checked an isolated OpenAI + AgentCore install.
- The 0.2.0 provider artifacts were built for all three providers targeting Linux ARM64/Python 3.14, with compatible native wheels and the corresponding example entrypoint. AWS CloudFormation `ValidateTemplate` accepts the example runtime template. These are packaging/template checks, not a new deployment.

CI repeats lint, format, tests, and package build on Python 3.14 (default), 3.13, and 3.12. Check the latest Actions run before relying on a particular commit.

## Verified in a hosted Gemini integration — September 25, 2026

A retail application consuming the exact 0.2.4 commit (`24d9f5e`) was deployed on
AgentCore with Python 3.14, Gemini 3.1 Flash Live, the existing Connect A2A bridge,
and an eight-second synthetic order delay. The application maps the library's
canonical attributes to its existing flow attribute names and verifies both copies.

Two concurrent real Connect WebRTC calls completed order lookup and escalation.
Order 1042 returned Shipped; both contacts had complete persistence, matching
subsequent-flow readback, distinct runtime sessions, and no failed or pending tools
in their private audits. The order tool took 8.350 seconds including persistence.
Both calls received audio and produced nonempty Connect IVR recordings. A two-second
soft-pulse reference matched the order recording with normalized correlation 0.993
after resampling 24 kHz to 8 kHz. Evidence remains in the deployment owner's private
store. This validates that integration; it does not deploy the generic template for
every account or establish every provider's behavior.

## Not yet established

- A live OpenAI provider call: no OpenAI API key was available during initial implementation.
- A live Nova 2 Sonic call for this new example; its AWS authentication/configuration and transport are covered offline.
- A PSTN-originated handset acceptance call for the new release; the hosted checks used Connect WebRTC.
- Complete transcript/tool-trace indexing and recording playback in a new user's Connect Contact details. These require account configuration and a real acceptance call.
- Production load, long-duration reconnect behavior across all providers, cross-region operation, or formal security review.
- A PyPI release. Install from GitHub for now.

## Known boundaries

Voice handoff only; not a generic text-chat/delegate A2A server. Audio remains mono PCM16 at the negotiated rate. Native voice still has Connect's immediate-handoff and Lex/Sonic setup requirements. Completion/escalation ends the collaboration; human routing is configured in your flow.

There is no acknowledged playback offset from Connect, so interruption markers distinguish generated speech from potentially heard speech without inventing exact truncation. Reconnect/history replay is delegated to Strands and needs provider-specific live testing. Prior history support seeds text turns; it does not reconstruct arbitrary binary/tool history from A2A data parts.

See [session duration and cleanup](session-lifecycle.md) for the five-minute cap, the absence of automatic wrap-up, and the distinction between bounded async waits and AWS operations that can complete later.

The contact name/description API is preview. The default examples leave it disabled. The package does not mutate arbitrary CTR fields, provision a full Connect instance/flow/ingress, or consume CTR exports. The scoped update APIs, trace events, and deployment instructions are the initial implementation.

## Next contributions

1. Real OpenAI/Nova 2 Sonic acceptance and additional Gemini interruption/reconnect scenarios with private evidence.
2. Reusable infrastructure for authenticated WSS ingress and Connect collaborator/flow registration.
3. Upstream public transport injection for Strands OpenAI and removal of compatibility overrides when fixed upstream.
4. More native voice providers and provider-specific interruption/reconnect tests.
5. Optional CTR streaming integration with idempotent downstream handling.
6. Trusted PyPI publishing and versioned releases after maintainer/release setup.
