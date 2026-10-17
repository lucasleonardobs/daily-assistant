# Daily assíncrona (MVP)

Assistente que conduz o check-in diário de cada pessoa do time por conversa e gera, sob demanda,
um report para o gestor (progresso, impeditivos, riscos e recomendações, sempre com evidência).

**Stack:** Python + [Google ADK 2](https://adk.dev) (agentes em grafo) + Gemini via Vertex AI ·
FastAPI · SQLite · Angular. A especificação está em `assistente de daily.md`.

## Onde está o agente

Tudo que é IA mora em `backend/agents/`. Leia nesta ordem:

| Arquivo | O que mostra |
| --- | --- |
| `agents/checkin_agent/agent.py` | O grafo do check-in (desenho em ASCII no topo do arquivo) |
| `agents/checkin_agent/nodes.py` | Os passos em código: carregar contexto, pedir confirmação, gravar |
| `agents/checkin_agent/prompts.py` | O que o LLM recebe |
| `agents/report_agent/agent.py` | O grafo do report: 3 analistas em paralelo, redator e revisor em loop |
| `agents/shared/safety.py` | Regras de conduta, dados-não-instruções e o plugin de segurança |

A regra do desenho: **o LLM decide o que perguntar e o que significa; o código decide quando cada etapa roda e o que pode ser gravado.**
Por isso o check-in só é gravado pela rota `confirm` do grafo (a pessoa confirma o resumo), o LLM não tem ferramentas
de banco, e a evidência do report é validada em código (`review_gate`), mesmo que o revisor aprove.

## Rodar local

```bash
# Backend (Python 3.11+, uv)
cd backend
cp .env.example .env        # ajuste GOOGLE_CLOUD_PROJECT / LOCATION; autentique com: gcloud auth application-default login
uv sync
uv run uvicorn app.main:app --reload      # http://localhost:8000 (API em /api, docs em /api/docs)

# Front-end (Node 20.19+ / 22.12+ / 24+)
cd frontend
npm install
npm start                                  # http://localhost:4200, com proxy para o backend
```

Em `DEV_MODE=true` o banco é populado com o time do protótipo e a barra lateral troca de usuário
(o front envia `X-User-Email`). Em produção, o acesso é por **e-mail e senha**, com links de convite de uso único
gerados pelo gestor (veja `docs/deploy-railway-aiven.md`).

Conversar com os agentes isoladamente, sem o front: `cd backend && uv run adk web agents`
(o estado `member_id`/`team_id` precisa existir na sessão; veja `load_context` em `nodes.py`).

## Testes

```bash
cd backend && uv run pytest
```

Os testes percorrem os dois grafos inteiros com um LLM falso (`tests/fake_llm.py`): pausa e retomada da confirmação,
loop de correção, fan-out/join do report, bloqueio de evidência inválida, permissões e isolamento de sessão.
**Nenhum teste chama o Gemini.**

## Build de produção

`docker build -t daily-assincrona .` gera um serviço único (Angular estático + API + agentes).
Banco Postgres via `DATABASE_URL`. Deploy em Railway + Aiven documentado em `docs/deploy-railway-aiven.md`.

## Desvios da especificação

- **SQLite** no lugar do Firestore (SQLAlchemy, para migrar depois sem reescrever).
- **Angular** no lugar de React.
- **Grafo ADK 2** (`Workflow`) no lugar de Sequential/Parallel/LoopAgent; confirmação humana como nó (`RequestInput`).
- **Sessões ADK em SQLite** (persistem entre reinícios; sem `max-instances=1`).
- A API roda os agentes dentro do próprio processo e entrega ao front eventos simples via SSE
  (`app/agent_runner.py`), em vez de expor as rotas `/run_sse` do ADK. Assim a identidade nunca vem do cliente.
- Participação e detalhe por pessoa do report são montados em código, não pelo LLM.
