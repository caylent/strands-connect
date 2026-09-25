# Changelog

## 0.2.3

Make long-tool demonstrations repeatable with an eight-second asynchronous lookup delay in all three example apps, configurable from 0–30 seconds at startup and through the deployment template. Keep the reusable adapter free of artificial tool delays. Pause the soft pulse during speech and resume after estimated queued playback while work remains pending. Verify simultaneous tool execution, outgoing cue audio, incoming caller audio, and cancellation on disconnect through the real Strands agent. Add a demo walkthrough.

## 0.2.2

Make the original soft-pulse ambient cue the default tool-wait sound across all providers. Wait 700 ms before starting, fade in, and loop without the old beep pause. Stop promptly when tools finish, speech resumes, or interruption occurs. Audio is synthesized locally and cached for each negotiated PCM rate.

## 0.2.1

Bound per-write waits (including queue time and readback) and the final contact-state update/store drain. Timeouts remain unverified even when an accepted AWS operation completes later. Forward the Sonic voice selection and document session caps, cleanup budgets, and the absence of automatic wrap-up. Remove stale current-version references.

## 0.2.0

Python 3.14 is now the default for local development, CI, and AgentCore deployment packages; Python 3.12/3.13 compatibility remains. Added a dedicated Amazon Nova 2 Sonic example using the runtime IAM role, provider-aware deployment permissions, and Sonic packaging/contract coverage.

## 0.1.0

Initial community extension: Connect native-voice transport; contact-scoped tools and async Strands hooks; deterministic mapped-result persistence with readback; contact name/description support; transcript/tool tracing; completion/escalation; optional tool earcon; OpenAI Realtime SDK and Gemini examples for AgentCore; optional Nova Sonic factory; offline behavioral and SDK protocol tests.
