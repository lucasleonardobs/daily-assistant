"""Modelos Gemini (Vertex AI) e configuração de geração dos agentes.

Os nomes dos modelos vêm de variáveis de ambiente (app.config), então dá para trocar
sem mudar código. Credenciais/projeto: GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_PROJECT
e GOOGLE_CLOUD_LOCATION (veja .env.example).
"""
from google.genai import types

from app.config import settings

MODEL_FAST = settings.model_fast    # conversa, extração, classificação
MODEL_SMART = settings.model_smart  # análise e escrita do report

_HARM_CATEGORIES = [
    types.HarmCategory.HARM_CATEGORY_HARASSMENT,
    types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
    types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
    types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
]


def generation_config(temperature: float = 0.2, model: object = None) -> types.GenerateContentConfig:
    """Filtros de segurança do Gemini ligados e, nos modelos antigos, temperatura baixa.

    Modelos Gemini 3 devem ficar na temperatura padrão (1.0): a documentação do Google avisa que valores
    menores podem causar repetição e perda de qualidade de raciocínio. Por isso, aqui ela é omitida.
    """
    keeps_default_temperature = isinstance(model, str) and model.startswith("gemini-3")
    return types.GenerateContentConfig(
        temperature=None if keeps_default_temperature else temperature,
        max_output_tokens=settings.max_output_tokens,
        safety_settings=[
            types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE)
            for c in _HARM_CATEGORIES
        ],
    )
