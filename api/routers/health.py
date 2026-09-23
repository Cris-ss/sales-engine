from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies import get_session
from api.errors import ApiError

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(session: Session = Depends(get_session)):
    try:
        session.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001
        raise ApiError(503, "banco_indisponivel", "Sem conectividade com o banco.") from exc
    return {"status": "ready"}
