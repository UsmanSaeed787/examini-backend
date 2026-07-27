from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.middleware.error_handler import setup_error_handlers
from app.api.routes import auth, admin, teacher, student, exams, materials
from app.ai.api.routes import router as ai_router
from app.ai.runtime.errors import setup_ai_error_handlers

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


@app.get("/")
async def root():
    return {
        "message": "Exam Management System API",
        "version": settings.app_version
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

