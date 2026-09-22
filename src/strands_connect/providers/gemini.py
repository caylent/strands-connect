"""Pinned Strands Gemini compatibility fixes, covered by provider-boundary tests."""

from google.genai import types
from strands.experimental.bidi.models.google import GoogleGeminiLiveModel


class GeminiLiveModel(GoogleGeminiLiveModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tool_names = {}

    def _convert_gemini_live_event(self, message, turn_state):
        if message.tool_call:
            for call in message.tool_call.function_calls or []:
                self._tool_names[call.id] = call.name
        # Audio transcription is the sole source of spoken-output history.
        # Strands 1.56 also treats model-turn text/thought parts as spoken text.
        if message.server_content and message.server_content.model_turn:
            message = message.model_copy(deep=True)
            message.server_content.model_turn.parts = [
                p for p in message.server_content.model_turn.parts or [] if p.inline_data
            ]
        return super()._convert_gemini_live_event(message, turn_state)

    async def _send_tool_result(self, tool_result):
        # Gemini requires the original function name, independently of its call ID.
        call_id = tool_result["toolUseId"]
        name = self._tool_names.pop(call_id)
        content = tool_result.get("content", [])
        response = content[0] if len(content) == 1 else {"result": content}
        await self._live_session.send_tool_response(
            function_responses=[types.FunctionResponse(id=call_id, name=name, response=response)]
        )
