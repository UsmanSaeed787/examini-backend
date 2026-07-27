from sqlalchemy.orm import Session
from uuid import UUID
from typing import List
from app.models.class_model import Class, Section, TeacherClass, StudentClass
from app.schemas.class_schema import ClassCreate, ClassUpdate, SectionCreate, SectionUpdate
from app.middleware.error_handler import NotFoundError, ValidationError


class ClassService:
    """Service for class and section management."""
    
    @staticmethod
    def create_class(db: Session, class_data: ClassCreate, created_by: UUID) -> Class:
        """Create a new class."""
        class_ = Class(
            name=class_data.name,
            description=class_data.description,
            created_by=created_by
        )
        db.add(class_)
        db.commit()
        db.refresh(class_)
        return class_
    
    @staticmethod
    def get_class(db: Session, class_id: UUID) -> Class:
        """Get class by ID."""
        class_ = db.query(Class).filter(Class.id == class_id).first()
        if not class_:
            raise NotFoundError("Class not found")
        return class_
    
    @staticmethod
    def get_all_classes(db: Session) -> List[Class]:
        """Get all classes."""
        return db.query(Class).all()
    
    @staticmethod
    def update_class(db: Session, class_id: UUID, class_data: ClassUpdate) -> Class:
        """Update class."""
        class_ = ClassService.get_class(db, class_id)
        
        if class_data.name:
            class_.name = class_data.name
        if class_data.description is not None:
            class_.description = class_data.description
        
        db.commit()
        db.refresh(class_)
        return class_
    
    @staticmethod
    def delete_class(db: Session, class_id: UUID):
        """Delete class."""
        class_ = ClassService.get_class(db, class_id)
        db.delete(class_)
        db.commit()
    
    @staticmethod
    def create_section(db: Session, class_id: UUID, section_data: SectionCreate) -> Section:
        """Create a section in a class."""
        # Verify class exists
        class_ = ClassService.get_class(db, class_id)
        
        section = Section(
            class_id=class_id,
            name=section_data.name,
            description=section_data.description
        )
        db.add(section)
        db.commit()
        db.refresh(section)
        return section
    
    @staticmethod
    def get_sections(db: Session, class_id: UUID) -> List[Section]:
        """Get all sections in a class."""
        return db.query(Section).filter(Section.class_id == class_id).all()
    
    @staticmethod
    def update_section(db: Session, section_id: UUID, section_data: SectionUpdate) -> Section:
        """Update section."""
        section = db.query(Section).filter(Section.id == section_id).first()
        if not section:
            raise NotFoundError("Section not found")
        
        if section_data.name:
            section.name = section_data.name
        if section_data.description is not None:
            section.description = section_data.description
        
        db.commit()
        db.refresh(section)
        return section
    
    @staticmethod
    def delete_section(db: Session, section_id: UUID):
        """Delete section."""
        section = db.query(Section).filter(Section.id == section_id).first()
        if not section:
            raise NotFoundError("Section not found")
        db.delete(section)
        db.commit()
    
    @staticmethod
    def assign_teacher_to_class(db: Session, teacher_id: UUID, class_id: UUID):
        """Assign teacher to class."""
        existing = db.query(TeacherClass).filter(
            TeacherClass.teacher_id == teacher_id,
            TeacherClass.class_id == class_id
        ).first()
        
        if existing:
            raise ValidationError("Teacher already assigned to this class")
        
        assignment = TeacherClass(teacher_id=teacher_id, class_id=class_id)
        db.add(assignment)
        db.commit()

