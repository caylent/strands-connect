"""Amazon Connect + AgentCore + Strands + Gemini Live."""

from examples.shared.application import create_app

app = create_app("gemini", "gemini-3.1-flash-live-preview")

if __name__ == "__main__":
    app.run(log_level="info")
