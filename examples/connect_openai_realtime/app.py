"""Amazon Connect + AgentCore + Strands + the official OpenAI Realtime SDK."""

from examples.shared.application import create_app

app = create_app("openai", "gpt-realtime")

if __name__ == "__main__":
    app.run(log_level="info")
