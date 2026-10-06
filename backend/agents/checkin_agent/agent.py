"""Grafo do check-in (ADK 2 Workflow).

    START → load_context → checkin_conversation → route_blockers
              ├─ has_blockers → blocker_classifier → merge_labels ─┐
              └─ no_blockers ──────────────────────────────────────┤
                                                                   ▼
            ask_confirmation (pausa: pessoa confirma ou corrige) → handle_review
              ├─ confirm → save_checkin
              ├─ correct → checkin_conversation   (volta à conversa; no máx. 3 vezes)
              └─ discard → discard_checkin        (limite de correções: termina SEM gravar)

Quem lê isto pela primeira vez: cada nome acima é uma função (nodes.py) ou um agente
LLM (abaixo). As setas são as `edges`; as rotas ("confirm", "correct"…) vêm de
`Event(route=...)` dentro dos nós.
"""
from google.adk import Agent, Workflow
from google.adk.apps import App

from agents.checkin_agent import nodes, prompts
from agents.shared.models import MODEL_FAST, generation_config
from agents.shared.safety import SafetyPlugin
from app.domain.schemas import BlockerLabels, CheckinDraft

def build_workflow(conversation_model=MODEL_FAST, classifier_model=MODEL_FAST) -> Workflow:
    """Monta o grafo. Os modelos são parâmetros para os testes usarem um LLM falso."""

    # Conversa até concluir a tarefa (mode="task") e entrega o resumo no schema CheckinDraft.
    # Sem ferramentas: todo o contexto já foi carregado em código (load_context).
    checkin_conversation = Agent(
        name="checkin_conversation",
        model=conversation_model,
        mode="task",
        instruction=prompts.CHECKIN,
        output_schema=CheckinDraft,
        generate_content_config=generation_config(temperature=0.4),
    )

    # Um único turno, sem conversa: rotula categoria e severidade dos bloqueios.
    blocker_classifier = Agent(
        name="blocker_classifier",
        model=classifier_model,
        mode="single_turn",
        instruction=prompts.CLASSIFIER,
        output_schema=BlockerLabels,
        generate_content_config=generation_config(temperature=0.0),
    )

    return Workflow(
        name="checkin_agent",
        edges=[
            ("START", nodes.load_context, checkin_conversation, nodes.route_blockers),
            (nodes.route_blockers, {
                "has_blockers": blocker_classifier,
                "no_blockers": nodes.ask_confirmation,
            }),
            (blocker_classifier, nodes.merge_labels, nodes.ask_confirmation),
            (nodes.ask_confirmation, nodes.handle_review),
            (nodes.handle_review, {
                "confirm": nodes.save_checkin,
                "correct": checkin_conversation,
                "discard": nodes.discard_checkin,
            }),
        ],
    )


def build_app(**models) -> App:
    return App(name="checkin_agent", root_agent=build_workflow(**models), plugins=[SafetyPlugin()])


root_agent = build_workflow()
app = App(name="checkin_agent", root_agent=root_agent, plugins=[SafetyPlugin()])
