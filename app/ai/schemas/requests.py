"""Request DTOs for the /api/ai surface."""
from typing import Optional

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    agent_key: str = Field(min_length=1, max_length=50)
    input: str = Field(min_length=1, max_length=20_000)
    session_id: Optional[str] = Field(default=None, max_length=100)
    background: bool = False
    agent_version: Optional[str] = Field(default=None, max_length=20)  # None = latest
