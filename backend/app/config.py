"""Configuração do app. Tudo vem de variáveis de ambiente (ou do arquivo .env)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    model_fast: str = "gemini-2.5-flash"   # conversa, extração, classificação
    model_smart: str = "gemini-2.5-pro"    # análise e escrita do report

    # Em dev, o usuário vem do header X-User-Email. Em produção, do header do IAP.
    dev_mode: bool = True

    db_path: str = str(BACKEND_DIR / "data" / "app.db")            # dados do produto
    sessions_db_path: str = str(BACKEND_DIR / "data" / "sessions.db")  # sessões do ADK

    aged_threshold_days: int = 2   # impeditivo acima disso sobe para o topo do report
    max_message_chars: int = 4000  # limite de tamanho de uma mensagem do usuário


settings = Settings()
