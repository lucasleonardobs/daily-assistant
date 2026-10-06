"""Check-in conversacional: contexto, sessão e mensagens (SSE) do agente."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import agent_runner
from app.api.deps import get_db, member_of_team, team_or_404
from app.db import repository as repo
from app.db.models import Checkin, Member, Team
from app.domain import rules

router = APIRouter(prefix="/api/teams/{team_id}/checkin", tags=["checkin"])


class SessionIn(BaseModel):
    fresh: bool = False  # True ao editar um check-in já confirmado


class ReviewIn(BaseModel):
    interrupt_id: str
    action: str = Field(pattern="^(confirm|correct)$")
    correction: str = Field(default="", max_length=2000)


class MessageIn(BaseModel):
    session_id: str
    text: str | None = Field(default=None, max_length=4000)
    review: ReviewIn | None = None
    invocation_id: str | None = None


@router.get("/context")
def context(team: Team = Depends(team_or_404), me: Member = Depends(member_of_team), db: Session = Depends(get_db)):
    """O que a tela mostra ao lado do chat: último plano, impeditivos abertos e o check-in de hoje."""
    cycle = repo.get_or_create_cycle(db, team)
    previous = repo.last_checkin_before(db, me.id, cycle.day)
    today = db.get(Checkin, f"{cycle.id}_{me.id}")
    names = {me.id: me.name}
    return {
        "first_name": me.name.split()[0],
        "previous": {"day": previous.day.isoformat(),
                     "planned": [p["summary"] for p in previous.data.get("planned", [])]} if previous else None,
        "open_impediments": [repo.impediment_view(i, cycle.day, names, 2)
                             for i in repo.open_impediments(db, team.id, me.id)],
        "today": {"confirmed_at": repo.utc_iso(today.confirmed_at), "version": today.version,
                  "data": today.data} if today else None,
    }


@router.post("/session")
async def session(body: SessionIn, team: Team = Depends(team_or_404), me: Member = Depends(member_of_team),
                  db: Session = Depends(get_db)):
    cycle = repo.get_or_create_cycle(db, team)
    db.commit()
    return {"session_id": await agent_runner.create_checkin_session(me, cycle.id, fresh=body.fresh)}


@router.post("/messages")
async def messages(body: MessageIn, team: Team = Depends(team_or_404), me: Member = Depends(member_of_team),
                   db: Session = Depends(get_db)):
    cycle = repo.get_or_create_cycle(db, team)
    if not body.session_id.startswith(f"{cycle.id}:{me.id}"):
        raise HTTPException(403, "Sessão não pertence a você neste time.")
    if not body.text and not body.review:
        raise HTTPException(422, "Envie texto ou a resposta ao resumo.")
    review = body.review.model_dump() if body.review else None
    db.commit()

    async def sse():
        async for event in agent_runner.stream_checkin(
                me.email, body.session_id, text=body.text, review=review, invocation_id=body.invocation_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
