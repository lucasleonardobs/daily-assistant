"""Grafo do report (ADK 2 Workflow). Acionado pelo botão "Gerar report" do gestor.

    START → load_report_context ─┬─ progress_analyst ─┐
                                 ├─ blocker_analyst ──┼→ join_analyses → collect_analyses
                                 └─ risk_analyst ─────┘          │
                                                                 ▼
       insights_agent → start_writing → report_writer → save_draft → report_critic → review_gate
                                            ▲                                           │
                                            └──────────── revise (até 3 voltas) ◄───────┤
                                                                              publish ──┴→ publish_report

O código (nodes.py) carrega dados, valida evidência e grava. Os agentes só interpretam e escrevem.
"""
from google.adk import Agent, Workflow
from google.adk.apps import App
from google.adk.workflow import JoinNode

from agents.report_agent import nodes, prompts
from agents.shared.models import MODEL_SMART, generation_config
from agents.shared.safety import SafetyPlugin
from app.domain.schemas import (BlockerAnalysis, Critique, ProgressAnalysis, Recommendations,
                                ReportDraft, RiskAnalysis)


def build_workflow(model=MODEL_SMART) -> Workflow:
    """Monta o grafo. O modelo é parâmetro para os testes usarem um LLM falso."""

    def llm(name: str, instruction: str, schema, temperature: float = 0.2) -> Agent:
        # single_turn: roda uma vez, sem conversar com o usuário.
        return Agent(name=name, model=model, mode="single_turn", instruction=instruction,
                     output_schema=schema, generate_content_config=generation_config(temperature))

    progress_analyst = llm("progress_analyst", prompts.PROGRESS, ProgressAnalysis)
    blocker_analyst = llm("blocker_analyst", prompts.BLOCKERS, BlockerAnalysis)
    risk_analyst = llm("risk_analyst", prompts.RISKS, RiskAnalysis)
    insights_agent = llm("insights_agent", prompts.INSIGHTS, Recommendations)
    report_writer = llm("report_writer", prompts.WRITER, ReportDraft, temperature=0.3)
    report_critic = llm("report_critic", prompts.CRITIC, Critique, temperature=0.0)
    join_analyses = JoinNode(name="join_analyses")

    return Workflow(
        name="report_agent",
        edges=[
            ("START", nodes.load_report_context,
             (progress_analyst, blocker_analyst, risk_analyst),  # fan-out: rodam em paralelo
             join_analyses, nodes.collect_analyses, insights_agent, nodes.start_writing,
             report_writer, nodes.save_draft, report_critic, nodes.review_gate),
            (nodes.review_gate, {"publish": nodes.publish_report, "revise": report_writer}),
        ],
    )


def build_app(**kwargs) -> App:
    return App(name="report_agent", root_agent=build_workflow(**kwargs), plugins=[SafetyPlugin()])


root_agent = build_workflow()
app = App(name="report_agent", root_agent=root_agent, plugins=[SafetyPlugin()])
