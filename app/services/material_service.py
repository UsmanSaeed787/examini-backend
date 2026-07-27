from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
from app.models.material import Material
from app.models.class_model import TeacherClass
from app.schemas.material import MaterialCreate, MaterialUpdate
from app.middleware.error_handler import NotFoundError, ValidationError, AuthorizationError
from app.utils.helpers import paginate_response


class MaterialService:
    """Service for material management operations."""

    @staticmethod
    def verify_teacher_class_access(db: Session, teacher_id: UUID, class_id: UUID) -> bool:
        """Verify that teacher has access to the class."""
        access = db.query(TeacherClass).filter(
            TeacherClass.teacher_id == teacher_id,
            TeacherClass.class_id == class_id
        ).first()
        return access is not None

    @staticmethod
    def create_material(
        db: Session,
        material_data: MaterialCreate,
        teacher_id: UUID,
        file_url: str,
        file_name: str,
        file_type: Optional[str] = None,
        file_size: Optional[int] = None
    ) -> Material:
        """Create a new material."""
        # Teachers can upload materials to any admin-created class
        # No need to verify teacher-class assignment
        
        # Verify class exists (from admin-created classes table)
        from app.models.class_model import Class
        class_ = db.query(Class).filter(Class.id == material_data.class_id).first()
        if not class_:
            from app.middleware.error_handler import NotFoundError
            raise NotFoundError("Class not found")

        material = Material(
            teacher_id=teacher_id,
            class_id=material_data.class_id,
            title=material_data.title,
            description=material_data.description,
            file_url=file_url,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            is_active=True
        )
        db.add(material)
        db.commit()
        db.refresh(material)
        return material

    @staticmethod
    def get_material(db: Session, material_id: UUID, teacher_id: UUID) -> Material:
        """Get material by ID, ensuring it belongs to the teacher."""
        material = db.query(Material).filter(Material.id == material_id).first()
        if not material:
            raise NotFoundError("Material not found")
        if material.teacher_id != teacher_id:
            raise AuthorizationError("You do not have access to this material")
        return material

    @staticmethod
    def get_materials(
        db: Session,
        teacher_id: UUID,
        class_id: Optional[UUID] = None,
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None
    ) -> dict:
        """Get paginated list of materials for a teacher."""
        query = db.query(Material).filter(Material.teacher_id == teacher_id)

        if class_id:
            # Filter by class - no access check needed, teachers can see all admin-created classes
            query = query.filter(Material.class_id == class_id)

        if search:
            query = query.filter(
                Material.title.ilike(f"%{search}%")
            )

        query = query.order_by(Material.uploaded_at.desc())

        total = query.count()
        materials = query.offset((page - 1) * limit).limit(limit).all()

        return paginate_response(materials, page, limit, total)

    @staticmethod
    def update_material(
        db: Session,
        material_id: UUID,
        material_data: MaterialUpdate,
        teacher_id: UUID
    ) -> Material:
        """Update material metadata."""
        material = MaterialService.get_material(db, material_id, teacher_id)

        update_data = material_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(material, field, value)

        db.commit()
        db.refresh(material)
        return material

    @staticmethod
    def delete_material(db: Session, material_id: UUID, teacher_id: UUID) -> None:
        """Delete a material (soft delete by setting is_active=False)."""
        material = MaterialService.get_material(db, material_id, teacher_id)
        material.is_active = False
        db.commit()

    @staticmethod
    def get_materials_by_ids(db: Session, material_ids: List[UUID], teacher_id: UUID) -> List[Material]:
        """Get materials by IDs, ensuring they belong to the teacher."""
        materials = db.query(Material).filter(
            Material.id.in_(material_ids),
            Material.teacher_id == teacher_id,
            Material.is_active == True
        ).all()
        return materials

