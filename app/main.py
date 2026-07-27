from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.middleware.error_handler import setup_error_handlers
from app.api.routes import auth, admin, teacher, student, exams, materials
from app.ai.api.routes import router as ai_router
from app.ai.runtime.errors import setup_ai_error_handlers
from app.database import SessionLocal, engine, Base
from app.models.user import User
from app.utils.security import get_password_hash
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Error handlers
setup_error_handlers(app)
setup_ai_error_handlers(app)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(teacher.router, prefix="/api/teachers", tags=["Teachers"])
app.include_router(student.router, prefix="/api/students", tags=["Students"])
app.include_router(exams.router, prefix="/api/exams", tags=["Exams"])
app.include_router(materials.router, prefix="/api/materials", tags=["Materials"])
app.include_router(ai_router, prefix="/api/ai", tags=["AI"])


@app.on_event("startup")
def auto_seed_admin():
    """Ensure tables exist and seed the default admin account on backend startup if missing."""
    try:
        # Create tables if not present
        Base.metadata.create_all(bind=engine)
        
        db = SessionLocal()
        try:
            admin_user = db.query(User).filter(User.email == "admin@examini.com").first()
            if not admin_user:
                logger.info("Auto-seeding default admin account (admin@examini.com)...")
                admin_user = User(
                    email="admin@examini.com",
                    password_hash=get_password_hash("Admin@123"),
                    role="admin",
                    full_name="System Administrator",
                    email_verified=True,
                    is_active=True,
                )
                db.add(admin_user)
                db.commit()
                logger.info("Default admin account auto-seeded successfully!")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Auto-seeding admin account skipped or failed: {e}")


@app.get("/")
async def root():
    return {
        "message": "Exam Management System API",
        "version": settings.app_version
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
