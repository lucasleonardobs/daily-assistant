"""LLM falso e roteirizado: permite testar os grafos sem chamar o Gemini."""
import json
from collections.abc import AsyncGenerator

from google.adk.models import BaseLlm, LlmCapabilities, LlmRequest, LlmResponse
from google.genai import types


class FakeLlm(BaseLlm):
    model: str = "fake"
    script: list = []  # cada item: str (texto), dict (JSON de output_schema) ou ("tool", nome, args)
    calls: int = 0

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, tuple):
            _, name, args = item
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        elif isinstance(item, dict):
            part = types.Part(text=json.dumps(item))
        else:
            part = types.Part(text=item)
        yield LlmResponse(content=types.Content(role="model", parts=[part]))

    @property
    def capabilities(self):
        return LlmCapabilities(output_schema_and_tools=False)  # como o Gemini 3 no ADK
