from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User

router = APIRouter()


@router.get("/{material_id}")
async def get_material(
    material_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get material details (role-based access)."""
    # TODO: Implement material retrieval with role-based filtering
    return {"message": "Not implemented yet"}

