"""Contratos de dados entre agentes, banco e API (Pydantic).

Os `output_schema` dos agentes usam estas classes: o Gemini é obrigado a responder
neste formato e o ADK valida antes de passar adiante.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Category = Literal[
    "DEPENDENCY_PERSON", "DEPENDENCY_TEAM", "ENVIRONMENT", "ACCESS",
    "REQUIREMENT_UNCLEAR", "TECHNICAL", "EXTERNAL", "OTHER",
]
Severity = Literal["LOW", "MEDIUM", "HIGH"]
RiskType = Literal["DEADLINE", "SCOPE", "QUALITY", "CAPACITY"]


# ---------------------------------------------------------------- check-in

class DoneItem(BaseModel):
    summary: str
    related_to_previous_plan: bool = Field(
        description="True se este item é o que a pessoa tinha planejado no check-in anterior."
    )


class PlannedItem(BaseModel):
    summary: str


class Blocker(BaseModel):
    summary: str
    category: Category = "OTHER"
    severity: Severity = "MEDIUM"
    needs_from: str = Field(default="", description="Pessoa, time ou sistema de quem a pessoa depende.")
    existing_impediment_id: int | None = Field(
        default=None, description="Id de um impeditivo já aberto, se este bloqueio for o mesmo."
    )


class Risk(BaseModel):
    summary: str
    type: RiskType


class CheckinDraft(BaseModel):
    """Resumo estruturado do check-in. Saída do agente de conversa."""

    done: list[DoneItem] = []
    planned: list[PlannedItem] = []
    blockers: list[Blocker] = []
    resolved_impediment_ids: list[int] = Field(
        default=[], description="Ids de impeditivos abertos que a pessoa disse ter destravado."
    )
    risks: list[Risk] = []
    notes: str = ""


class BlockerLabel(BaseModel):
    index: int = Field(description="Posição do bloqueio na lista recebida (começa em 0).")
    category: Category
    severity: Severity
    existing_impediment_id: int | None = None


class BlockerLabels(BaseModel):
    """Saída do classificador de bloqueios."""

    labels: list[BlockerLabel] = []


class ReviewDecision(BaseModel):
    """Resposta da pessoa ao resumo: confirmar ou corrigir."""

    action: Literal["confirm", "correct"]
    correction: str = ""

    @field_validator("correction", mode="before")
    @classmethod
    def _none_is_empty(cls, v):  # o cliente pode omitir o campo; o ADK preenche com None
        return v or ""


# ------------------------------------------------------------------ report

class ProgressItem(BaseModel):
    text: str
    evidence_ids: list[str] = Field(description="Ids dos check-ins de origem. Obrigatório.")


class ProgressTheme(BaseModel):
    theme: str
    items: list[ProgressItem]


class ProgressAnalysis(BaseModel):
    themes: list[ProgressTheme] = []


class ImpedimentFinding(BaseModel):
    summary: str
    severity: Severity
    status: Literal["NEW", "OPEN", "RESOLVED"]
    age_label: str = ""
    evidence_ids: list[str]


class BlockerAnalysis(BaseModel):
    findings: list[ImpedimentFinding] = []
    shared_dependencies: list[str] = Field(
        default=[], description="Dependências comuns ou cruzadas entre pessoas, com evidência."
    )


class RiskFinding(BaseModel):
    type: Literal["Repetição", "Plano não cumprido", "Dependência", "Padrão"]
    text: str
    evidence_ids: list[str]


class RiskAnalysis(BaseModel):
    risks: list[RiskFinding] = []


class Recommendation(BaseModel):
    text: str = Field(description="Ação concreta, sem cobrança individual nem culpa.")
    tag: str = Field(description="Ex.: 'Alta · 3 dias úteis', 'Dependência'.")
    high_priority: bool
    suggested_owner: str
    evidence_ids: list[str]


class Recommendations(BaseModel):
    items: list[Recommendation] = Field(default=[], max_length=5)


class ReportDraft(BaseModel):
    """Saída do redator. Participação e detalhe por pessoa são montados em código."""

    actions: list[Recommendation] = Field(max_length=5)
    progress: list[ProgressTheme]
    impediments: list[ImpedimentFinding]
    risks: list[RiskFinding]


class Critique(BaseModel):
    approved: bool
    problems: list[str] = Field(
        default=[], description="O que corrigir. Vazio se aprovado."
    )
