from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User

router = APIRouter()


@router.get("/{exam_id}")
async def get_exam(
    exam_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get exam details (role-based access)."""
    # TODO: Implement exam retrieval with role-based filtering
    return {"message": "Not implemented yet"}

