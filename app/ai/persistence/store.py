"""Synchronous run/session store. All functions open their own short-lived
DB session and are invoked from async code via asyncio.to_thread."""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from app.ai.persistence.models import AIMessage, AIRun, AIUsage
from app.database import SessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- runs

def create_run(
    user_id: UUID,
    agent_key: str,
    input_summary: Optional[str] = None,
    session_id: Optional[str] = None,
    status: str = "queued",
) -> UUID:
    with SessionLocal() as db:
        run = AIRun(
            user_id=user_id,
            agent_key=agent_key,
            status=status,
            session_id=session_id,
            input_summary=(input_summary or "")[:2000] or None,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id


def mark_running(run_id: UUID) -> None:
    with SessionLocal() as db:
        run = db.query(AIRun).filter(AIRun.id == run_id).first()
        if run:
            run.status = "running"
            run.started_at = _now()
            db.commit()


def complete_run(run_id: UUID, output_summary: Optional[str], usage: dict, model: Optional[str]) -> None:
    with SessionLocal() as db:
        run = db.query(AIRun).filter(AIRun.id == run_id).first()
        if not run:
            return
        run.status = "completed"
        run.output_summary = output_summary
        run.finished_at = _now()
        db.add(
            AIUsage(
                run_id=run_id,
                user_id=run.user_id,
                model=model,
                requests=usage.get("requests", 0),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )
        )
        db.commit()


def fail_run(run_id: UUID, error_code: str, error_message: str) -> None:
    with SessionLocal() as db:
        run = db.query(AIRun).filter(AIRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.error_code = error_code
            run.error_message = error_message[:2000]
            run.finished_at = _now()
            db.commit()


def get_run(run_id: UUID, user_id: UUID) -> Optional[dict]:
    """Fetch a run the given user owns (row-scoped read)."""
    with SessionLocal() as db:
        run = db.query(AIRun).filter(AIRun.id == run_id, AIRun.user_id == user_id).first()
        if not run:
            return None
        usage = db.query(AIUsage).filter(AIUsage.run_id == run_id).first()
        return {
            "run_id": run.id,
            "agent_key": run.agent_key,
            "status": run.status,
            "session_id": run.session_id,
            "output_summary": run.output_summary,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "created_at": run.created_at,
            "finished_at": run.finished_at,
            "usage": {
                "requests": usage.requests,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            }
            if usage
            else None,
        }


# ---------------------------------------------------------------- agent state

def get_agent_states() -> dict:
    """agent_key -> enabled, for keys with an explicit record."""
    from app.ai.persistence.models import AIAgentState

    with SessionLocal() as db:
        return {row.agent_key: bool(row.enabled) for row in db.query(AIAgentState).all()}


def get_agent_enabled(agent_key: str) -> Optional[bool]:
    """Explicit flag for one agent, or None when no record exists."""
    from app.ai.persistence.models import AIAgentState

    with SessionLocal() as db:
        row = db.query(AIAgentState).filter(AIAgentState.agent_key == agent_key).first()
        return bool(row.enabled) if row else None


def set_agent_enabled(agent_key: str, enabled: bool, actor_id: Optional[UUID]) -> None:
    from app.ai.persistence.models import AIAgentState

    with SessionLocal() as db:
        row = db.query(AIAgentState).filter(AIAgentState.agent_key == agent_key).first()
        if row is None:
            row = AIAgentState(agent_key=agent_key)
            db.add(row)
        row.enabled = enabled
        row.updated_by = actor_id
        row.updated_at = _now()
        db.commit()


# ---------------------------------------------------------------- quota reads

def runs_today(user_id: UUID) -> int:
    start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        return (
            db.query(AIRun)
            .filter(AIRun.user_id == user_id, AIRun.created_at >= start)
            .count()
        )


def tokens_today(user_id: UUID) -> int:
    from sqlalchemy import func

    start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        total = (
            db.query(func.coalesce(func.sum(AIUsage.total_tokens), 0))
            .filter(AIUsage.user_id == user_id, AIUsage.created_at >= start)
            .scalar()
        )
        return int(total or 0)


# ---------------------------------------------------------------- session items

def get_session_items(session_id: str, limit: Optional[int] = None) -> List[dict]:
    with SessionLocal() as db:
        query = (
            db.query(AIMessage)
            .filter(AIMessage.session_id == session_id)
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
        )
        if limit:
            query = query.limit(limit)
        rows = list(reversed(query.all()))
        return [row.item for row in rows]


def add_session_items(session_id: str, items: List[dict], run_id: Optional[UUID] = None) -> None:
    if not items:
        return
    with SessionLocal() as db:
        for item in items:
            db.add(AIMessage(session_id=session_id, run_id=run_id, item=item))
        db.commit()


def pop_session_item(session_id: str) -> Optional[dict]:
    with SessionLocal() as db:
        row = (
            db.query(AIMessage)
            .filter(AIMessage.session_id == session_id)
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
            .first()
        )
        if not row:
            return None
        item = row.item
        db.delete(row)
        db.commit()
        return item


def clear_session(session_id: str) -> None:
    with SessionLocal() as db:
        db.query(AIMessage).filter(AIMessage.session_id == session_id).delete()
        db.commit()
