"""Configuração do app. Tudo vem de variáveis de ambiente (ou do arquivo .env)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Modelo mais barato disponível (US$ 0,25 / US$ 1,50 por 1M tokens). O 2.5-flash-lite sai de linha em 16/10/2026.
    model_fast: str = "gemini-3.1-flash-lite"   # conversa, extração, classificação
    model_smart: str = "gemini-3.1-flash-lite"  # análise e escrita do report (troque por um modelo maior se a qualidade pedir)

    # --- Banco -------------------------------------------------------------
    # Produção: DATABASE_URL do Postgres (ex.: Aiven). Vazio = SQLite local (dev/testes).
    database_url: str | None = None
    db_path: str = str(BACKEND_DIR / "data" / "app.db")                # SQLite: dados do produto
    sessions_db_path: str = str(BACKEND_DIR / "data" / "sessions.db")  # SQLite: sessões do ADK
    db_pool_size: int = 3     # o plano gratuito da Aiven permite só 20 conexões no total
    db_max_overflow: int = 2

    # --- Acesso ------------------------------------------------------------
    # Dev: o usuário vem do header X-User-Email e há seletor de usuário na tela.
    # Produção (DEV_MODE=false): login próprio (e-mail + senha) e cookie de sessão assinado.
    dev_mode: bool = True
    secret_key: str = "dev-only-change-me"  # assina o cookie de sessão; OBRIGATÓRIO em produção
    session_hours: int = 12
    cookie_secure: bool = True            # cookie só por HTTPS (desligue só em http://localhost)
    public_base_url: str | None = None    # usado nos links de convite; padrão: o endereço da própria requisição
    invite_hours: int = 72                # validade do link de primeiro acesso / redefinição de senha
    max_failed_logins: int = 5            # após isso a conta fica bloqueada por `lockout_minutes`
    lockout_minutes: int = 15

    # --- Primeiro acesso em produção ---------------------------------------
    # Se o banco estiver vazio, cria este time com este gestor (não há seed em produção) e registra
    # no log um link de convite de uso único para ele definir a senha.
    bootstrap_manager_email: str | None = None
    bootstrap_manager_name: str = "Gestor"
    bootstrap_team_name: str = "Meu time"

    # --- Travas de custo (cada chamada de LLM custa) ---------------------------
    max_llm_calls_checkin: int = 25     # por execução do grafo de check-in (o normal são ~5)
    max_llm_calls_report: int = 30      # por execução do grafo de report (o normal são ~7-11)
    max_output_tokens: int = 8192       # teto de saída por chamada
    max_checkin_messages: int = 40      # mensagens por conversa de check-in
    max_reports_per_day: int = 10       # gerações de report por time por dia

    aged_threshold_days: int = 2   # impeditivo acima disso é tratado como prioridade no report
    max_message_chars: int = 4000  # limite de tamanho de uma mensagem do usuário


settings = Settings()
