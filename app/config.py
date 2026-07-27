from pydantic_settings import BaseSettings
from typing import List
from pydantic import field_validator


class Settings(BaseSettings):
    # Database
    database_url: str

    # Supabase (legacy — no longer used; kept optional for backward compat)
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_role_key: str = ""
    
    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    
    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Cloudinary (file storage)
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    
    # App
    app_name: str = "Exam Management System"
    app_version: str = "1.0.0"
    debug: bool = True
    cors_origins: str = "http://localhost:3000,https://examini-indol.vercel.app,*"
    
    # File Upload
    max_file_size_mb: int = 50
    allowed_file_types: str = "pdf,doc,docx,txt,png,jpg,jpeg"
    upload_dir: str = "uploads"
    
    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse comma-separated CORS origins string to list for internal use."""
        # Handle both list and string inputs
        if isinstance(v, list):
            return ','.join(str(item) for item in v)
        if isinstance(v, str):
            return v
        return "http://localhost:3000"
    
    @field_validator('allowed_file_types', mode='before')
    @classmethod
    def parse_file_types(cls, v):
        """Parse comma-separated file types string for internal use."""
        # Handle both list and string inputs
        if isinstance(v, list):
            return ','.join(str(item) for item in v)
        if isinstance(v, str):
            return v
        return "pdf,doc,docx,txt"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]
    
    @property
    def allowed_file_types_list(self) -> List[str]:
        """Get allowed file types as a list."""
        return [ftype.strip() for ftype in self.allowed_file_types.split(',') if ftype.strip()]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # tolerate AI_* and other namespaced keys in the shared .env


settings = Settings()

