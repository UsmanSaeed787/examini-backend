"""Question-bank tools — wrap QuestionBankService."""
from typing import List, Optional

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolContext, tool
from app.middleware.error_handler import ValidationError
from app.services.question_bank_service import QuestionBankService
from app.utils.constants import DifficultyLevel, QuestionType


class SaveQuestionParams(BaseModel):
    question_text: str = Field(min_length=1, description="The question text to save")
    question_type: str = Field(description="mcq | short_answer | long_answer | true_false")
    difficulty_level: Optional[str] = Field(default=None, description="easy | medium | hard")
    tags: Optional[List[str]] = Field(default=None, description="Optional tags for retrieval")


class ListBankQuestionsParams(BaseModel):
    search: Optional[str] = Field(default=None, description="Filter by text match")
    tag: Optional[str] = Field(default=None, description="Filter by tag")


@tool(
    key="question_bank.save",
    description="Save a reusable question to the calling teacher's question bank.",
    params=SaveQuestionParams,
    services=("QuestionBankService",),
    tags=("question-bank", "write"),
)
def save_question(ctx: ToolContext, params: SaveQuestionParams) -> dict:
    try:
        q_type = QuestionType(params.question_type)
        difficulty = DifficultyLevel(params.difficulty_level) if params.difficulty_level else None
    except ValueError as exc:
        raise ValidationError(str(exc))
    with ctx.db() as db:
        entry = QuestionBankService.add_question(
            db, ctx.identity.user_id, params.question_text, q_type, difficulty, params.tags
        )
        return {"id": str(entry.id), "saved": True}


@tool(
    key="question_bank.list",
    description="List questions from the calling teacher's question bank (optionally filtered by text or tag).",
    params=ListBankQuestionsParams,
    services=("QuestionBankService",),
    tags=("question-bank", "read"),
)
def list_bank_questions(ctx: ToolContext, params: ListBankQuestionsParams) -> list[dict]:
    with ctx.db() as db:
        entries = QuestionBankService.list_questions(
            db, ctx.identity.user_id, search=params.search, tag=params.tag
        )
        return [
            {
                "id": str(e.id),
                "question_text": e.question_text,
                "question_type": e.question_type,
                "difficulty_level": e.difficulty_level,
                "tags": list(e.tags or []),
            }
            for e in entries
        ]
