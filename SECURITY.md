# Security

Do not include credentials, transcripts containing personal data, or private account details in public issues. Use GitHub's private vulnerability reporting feature when enabled, or contact a repository maintainer privately to arrange a report.

Deploy behind authenticated TLS ingress. AgentCore IAM authentication protects the runtime, while the optional bridge verifies Connect's bearer secret. Scope Connect permissions to your instance, store provider keys in Secrets Manager, and use synthetic data until your retention and redaction requirements are configured.

Version 0.1 is an early integration. See `docs/verification.md` for explicit limits and acceptance gaps.
