"""Amazon Connect + AgentCore + Strands + Amazon Nova 2 Sonic."""

from examples.shared.application import create_app

app = create_app("sonic", "amazon.nova-2-sonic-v1:0")

if __name__ == "__main__":
    app.run(log_level="info")
