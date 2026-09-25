# Changelog

## 0.2.1

Bound per-write waits (including queue time and readback) and the final contact-state update/store drain. Timeouts remain unverified even when an accepted AWS operation completes later. Forward the Sonic voice selection and document session caps, cleanup budgets, and the absence of automatic wrap-up. Remove stale current-version references.

## 0.2.0

Python 3.14 is now the default for local development, CI, and AgentCore deployment packages; Python 3.12/3.13 compatibility remains. Added a dedicated Amazon Nova 2 Sonic example using the runtime IAM role, provider-aware deployment permissions, and Sonic packaging/contract coverage.

## 0.1.0

Initial community extension: Connect native-voice transport; contact-scoped tools and async Strands hooks; deterministic mapped-result persistence with readback; contact name/description support; transcript/tool tracing; completion/escalation; optional tool earcon; OpenAI Realtime SDK and Gemini examples for AgentCore; optional Nova Sonic factory; offline behavioral and SDK protocol tests.
