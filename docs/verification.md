# Verification and limitations

Initial implementation checked September 22, 2026; Python 3.14 / Nova 2 Sonic, bounded-write, and soft-pulse updates checked September 25, 2026. This page separates implementation tests from live service acceptance.

## Verified locally

- Behavioral tests run with the real pinned Strands `BidiAgent`, its tool executor, public hooks, and local WebSockets. AWS responses and voice generation are simulated in these acceptance fixtures.
- The 24 kHz OpenAI and 16/24 kHz Gemini/Nova 2 Sonic profiles negotiate audio, execute order lookup, persist mapped results before returning them to the model, emit tool/transcript traces, and finish or escalate with saved notes.
- The **actual official OpenAI Python SDK** connects to a local protocol server; session configuration, audio events, streamed function calls, and connection cleanup are exercised without an external API key.
- AgentCore's actual ASGI application is exercised locally for health, runtime-session context, and first-message handling. The bearer-to-runtime bridge is tested over WebSockets for authentication, A2A headers, correlation, and forwarding.
- Contact ownership and initial/current leg separation, concurrent contact isolation, allowlists, write/readback failures, cancelled waiters, queue saturation, per-write deadlines (including queue time and readback), late AWS completion, and shared final contact-cleanup deadlines are covered.
- Audio readiness, soft-pulse PCM levels and loop seams at all negotiated rates, quick-call silence, continuous looping, prompt cue cancellation on tool completion/speech/interruption, interruption markers, final trace ordering, frame fragmentation, DTMF completion, and Gemini compatibility behavior are covered.
- All 55 behavioral tests pass on Python 3.14.3, including Sonic voice selection in the actual provider configuration event. Wheel/source distribution builds pass. The 0.2.0 verification also checked a clean Sonic + AgentCore wheel installation without OpenAI or Gemini packages; the initial implementation checked an isolated OpenAI + AgentCore install.
- The 0.2.0 provider artifacts were built for all three providers targeting Linux ARM64/Python 3.14, with compatible native wheels and the corresponding example entrypoint. AWS CloudFormation `ValidateTemplate` accepts the example runtime template. These are packaging/template checks, not a new deployment.

CI repeats lint, format, tests, and package build on Python 3.14 (default), 3.13, and 3.12. Check the latest Actions run before relying on a particular commit.

## Not yet established for this extracted library

- A live OpenAI provider call: no OpenAI API key was available during initial implementation.
- A live Nova 2 Sonic call for this new example; its AWS authentication/configuration and transport are covered offline.
- A new hosted AgentCore + Connect deployment of this exact library, including the Python 3.14 runtime. The existing Gemini prototype informed the extraction, but its earlier live results do not validate all new library changes.
- Complete transcript/tool-trace indexing and recording playback in a new user's Connect Contact details. These require account configuration and a real acceptance call.
- Production load, long-duration reconnect behavior across all providers, cross-region operation, or formal security review.
- A PyPI release. Install from GitHub for now.

## Known boundaries

Voice handoff only; not a generic text-chat/delegate A2A server. Audio remains mono PCM16 at the negotiated rate. Native voice still has Connect's immediate-handoff and Lex/Sonic setup requirements. Completion/escalation ends the collaboration; human routing is configured in your flow.

There is no acknowledged playback offset from Connect, so interruption markers distinguish generated speech from potentially heard speech without inventing exact truncation. Reconnect/history replay is delegated to Strands and needs provider-specific live testing. Prior history support seeds text turns; it does not reconstruct arbitrary binary/tool history from A2A data parts.

See [session duration and cleanup](session-lifecycle.md) for the five-minute cap, the absence of automatic wrap-up, and the distinction between bounded async waits and AWS operations that can complete later.

The contact name/description API is preview. The default examples leave it disabled. The package does not mutate arbitrary CTR fields, provision a full Connect instance/flow/ingress, or consume CTR exports. The scoped update APIs, trace events, and deployment instructions are the initial implementation.

## Next contributions

1. Real OpenAI and fresh Gemini acceptance with a dedicated test flow and private evidence.
2. Reusable infrastructure for authenticated WSS ingress and Connect collaborator/flow registration.
3. Upstream public transport injection for Strands OpenAI and removal of compatibility overrides when fixed upstream.
4. More native voice providers and provider-specific interruption/reconnect tests.
5. Optional CTR streaming integration with idempotent downstream handling.
6. Trusted PyPI publishing and versioned releases after maintainer/release setup.
