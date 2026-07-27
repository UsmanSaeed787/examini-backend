"""Material tools — wrap MaterialService + ParserService (teacher-scoped).
Registered in the Tool Registry; agents resolve them by key."""
from typing import List, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.tools import _base
from app.ai.tools.registry import ToolContext, tool
from app.middleware.error_handler import ValidationError
from app.services.material_service import MaterialService
from app.services.parser_service import ParserService


class ListMaterialsParams(BaseModel):
    class_id: Optional[str] = Field(default=None, description="Optional class id (UUID) to filter by")


class GetMaterialTextParams(BaseModel):
    material_id: str = Field(description="Material id (UUID)")


@tool(
    key="materials.list",
    description="List the calling teacher's uploaded course materials (optionally filtered by class id).",
    params=ListMaterialsParams,
    services=("MaterialService",),
    tags=("materials", "read"),
)
def list_materials(ctx: ToolContext, params: ListMaterialsParams) -> list[dict]:
    with ctx.db() as db:
        page = MaterialService.get_materials(
            db,
            teacher_id=ctx.identity.user_id,
            class_id=UUID(params.class_id) if params.class_id else None,
            page=1,
            limit=50,
        )
        return [
            {
                "id": str(m.id),
                "title": m.title,
                "file_name": m.file_name,
                "file_type": m.file_type,
                "class_id": str(m.class_id),
            }
            for m in page["items"]
        ]


@tool(
    key="materials.get_text",
    description="Fetch the extracted plain text of one of the calling teacher's materials (pdf/docx/txt only).",
    params=GetMaterialTextParams,
    services=("MaterialService", "ParserService"),
    tags=("materials", "read"),
)
def get_material_text(ctx: ToolContext, params: GetMaterialTextParams) -> dict:
    with ctx.db() as db:
        material = MaterialService.get_material(db, UUID(params.material_id), ctx.identity.user_id)
        try:
            text = ParserService.extract_text(material)
        except ValueError as exc:
            raise ValidationError(str(exc))
        return {"id": str(material.id), "title": material.title, "text": text}


def extract_teacher_material_texts(
    teacher_id: UUID, material_ids: List[UUID]
) -> List[Tuple[str, str]]:
    """Deterministic helper used by the facade (not exposed to the model):
    fetch owned materials and extract their text. Raises ValidationError on
    missing/unreadable materials — mirroring the legacy route's checks."""
    with _base.db_session() as db:
        materials = MaterialService.get_materials_by_ids(db, material_ids, teacher_id)
        if len(materials) != len(material_ids):
            raise ValidationError("Some materials not found or not accessible")
        texts: List[Tuple[str, str]] = []
        for material in materials:
            try:
                texts.append((material.title, ParserService.extract_text(material)))
            except ValueError as exc:
                raise ValidationError(str(exc))
        return texts
