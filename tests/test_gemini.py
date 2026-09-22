from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai import types
from strands.experimental.bidi.models.google import _TurnState

from strands_connect.providers.gemini import GeminiLiveModel


def test_spoken_transcript_excludes_model_text_and_thought_parts():
    model = GeminiLiveModel(model_id="test", client_args={"api_key": "test-only"})
    state = _TurnState()
    message = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(parts=[types.Part(text="private model text", thought=True)]),
            output_transcription=types.Transcription(text="Hello there."),
        )
    )
    events = model._convert_gemini_live_event(message, state)
    assert state.output_transcript == "Hello there."
    assert all("private model text" not in str(event) for event in events)


@pytest.mark.asyncio
async def test_tool_response_preserves_function_name_separate_from_id():
    model = GeminiLiveModel(model_id="test", client_args={"api_key": "test-only"})
    model._live_session = SimpleNamespace(send_tool_response=AsyncMock())
    model._tool_names["call-123"] = "lookup_order"
    await model._send_tool_result({"toolUseId": "call-123", "content": [{"json": {"status": "Shipped"}}]})
    response = model._live_session.send_tool_response.call_args.kwargs["function_responses"][0]
    assert response.id == "call-123" and response.name == "lookup_order"
