from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from uuid import UUID
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.database import get_db
from app.api.deps import get_student_user
from app.models.user import User
from app.models.exam import Exam, Question, QuestionOption
from app.models.attempt import ExamAttempt, ExamResponse, ExamResult
from app.models.material import Material
from app.models.class_model import StudentClass
from app.schemas.common import DashboardStats, PaginatedResponse, MessageResponse
from app.schemas.exam import ExamResponse as ExamResponseSchema, ExamDetailResponse
from app.schemas.result import ExamSubmit, ExamAttemptResponse, ExamResultResponse
from app.schemas.material import MaterialResponse
from app.services.student_service import StudentService
from app.services.exam_service import ExamService
from app.services.material_service import MaterialService
from app.services.storage_service import StorageService
from app.utils.constants import UserRole, ExamAttemptStatus, QuestionType
from app.utils.helpers import calculate_grade
from app.middleware.error_handler import NotFoundError, ValidationError
from app.config import settings

router = APIRouter()


def calculate_and_save_result(db: Session, exam_id: UUID, attempt_id: UUID) -> ExamResult:
    """
    Calculate exam result from exam_responses table and save to exam_results table.
    
    Steps:
    1. Get all responses from exam_responses table for this attempt_id
    2. For each response, verify/calculate is_correct and points_earned
    3. Calculate total_score from all responses' points_earned
    4. Calculate max_score from all questions in the exam
    5. Calculate percentage
    6. Create/Update result in exam_results table
    """
    # Step 1: Get all responses from exam_responses table
    print(f"\n=== Calculating result for attempt_id={attempt_id}, exam_id={exam_id} ===")
    all_responses = db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt_id).all()
    print(f"Found {len(all_responses)} responses in exam_responses table")
    
    if not all_responses:
        raise HTTPException(status_code=400, detail="No responses found for this attempt")
    
    # Step 2: Get all questions for this exam
    all_questions = db.query(Question).filter(Question.exam_id == exam_id).all()
    question_map = {q.id: q for q in all_questions}
    
    # Step 3: ALWAYS recalculate is_correct and points_earned for each response from scratch
    for response in all_responses:
        question = question_map.get(response.question_id)
        if not question:
            print(f"Warning: Question {response.question_id} not found for exam {exam_id}")
            continue
        
        # Always recalculate is_correct for MCQ and True/False questions
        if question.question_type in [QuestionType.MCQ.value, QuestionType.TRUE_FALSE.value]:
            # Get correct options
            correct_options = db.query(QuestionOption).filter(
                and_(
                    QuestionOption.question_id == question.id,
                    QuestionOption.is_correct == True
                )
            ).all()
            correct_ids = {str(opt.id) for opt in correct_options}
            
            # Get selected options from response
            selected_ids = {str(opt) for opt in (response.selected_options or [])}
            
            # Debug logging
            print(f"Recalculating response {response.id}: correct_ids={correct_ids}, selected_ids={selected_ids}")
            
            # Check if correct (exact match required)
            if len(correct_ids) > 0:
                response.is_correct = (correct_ids == selected_ids)
            else:
                response.is_correct = False
            
            # Update points_earned based on is_correct
            if response.is_correct:
                response.points_earned = question.points
                print(f"Response {response.id}: CORRECT - {question.points} points")
            else:
                response.points_earned = 0
                print(f"Response {response.id}: INCORRECT - 0 points")
        else:
            # Text answer - needs review, set to None
            response.is_correct = None
            response.points_earned = 0
    
    # Commit response updates
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error updating responses: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating responses: {str(e)}")
    
    # Step 4: Calculate total_score from all responses' points_earned
    total_score = sum(float(response.points_earned or 0) for response in all_responses)
    
    # Step 5: Calculate max_score from all questions in the exam
    max_score = sum(float(q.points) for q in all_questions)
    
    # Step 6: Calculate percentage
    percentage = (total_score / max_score * 100) if max_score > 0 else 0
    
    # Step 6.5: Calculate grade based on percentage
    grade, passed = calculate_grade(float(percentage))
    
    # Debug logging - detailed breakdown
    print(f"\n=== Result Calculation Summary ===")
    print(f"Total responses: {len(all_responses)}")
    print(f"Total questions: {len(all_questions)}")
    for i, response in enumerate(all_responses, 1):
        question = question_map.get(response.question_id)
        q_points = question.points if question else 0
        earned = float(response.points_earned or 0)
        is_correct_str = "CORRECT" if response.is_correct else ("INCORRECT" if response.is_correct is False else "NEEDS REVIEW")
        print(f"  Response {i}: {earned}/{q_points} points ({is_correct_str})")
    print(f"\nTotal score: {total_score}")
    print(f"Max score: {max_score}")
    print(f"Percentage: {percentage}%")
    print(f"Grade: {grade}")
    print(f"Passed: {passed}")
    print(f"===============================\n")
    
    # Step 7: Create or update result in exam_results table
    existing_result = db.query(ExamResult).filter(ExamResult.attempt_id == attempt_id).first()
    
    if existing_result:
        # Update existing result
        print(f"Updating existing result {existing_result.id} in exam_results table")
        existing_result.total_score = total_score
        existing_result.max_score = max_score
        existing_result.percentage = percentage
        existing_result.grade = grade
        existing_result.passed = passed
        try:
            db.commit()
            db.refresh(existing_result)
            print(f"Result updated successfully: {existing_result.total_score}/{existing_result.max_score} = {existing_result.percentage}%")
            return existing_result
        except Exception as e:
            db.rollback()
            print(f"Error updating result in exam_results table: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error updating result: {str(e)}")
    else:
        # Create new result
        print(f"Creating new result in exam_results table for attempt {attempt_id}")
        try:
            result = ExamResult(
                attempt_id=attempt_id,
                total_score=total_score,
                max_score=max_score,
                percentage=percentage,
                grade=grade,
                passed=passed
            )
            db.add(result)
            db.commit()
            db.refresh(result)
            print(f"Result created successfully: {result.total_score}/{result.max_score} = {result.percentage}%")
            return result
        except Exception as e:
            db.rollback()
            print(f"Error creating result in exam_results table: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error creating result: {str(e)}")


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Get student dashboard data."""
    stats = StudentService.get_dashboard_stats(db, current_user.id)
    return DashboardStats(**stats)


@router.get("/exams", response_model=PaginatedResponse)
async def list_exams(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """List available exams for student."""
    # Debug: Check student's enrolled classes
    class_ids = StudentService.get_student_classes(db, current_user.id)
    if not class_ids:
        # Return empty response with message in total
        return PaginatedResponse(
            items=[],
            total=0,
            page=page,
            limit=limit,
            pages=0
        )
    
    result = StudentService.get_available_exams(
        db, current_user.id, status, page, limit
    )
    return PaginatedResponse(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.get("/exams/{exam_id}", response_model=dict)
async def get_exam(
    exam_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Get exam details for student (with questions but without correct answers)."""
    # Verify exam exists and is published
    exam = ExamService.get_exam(db, exam_id)
    
    if not exam.is_published:
        raise HTTPException(status_code=403, detail="Exam is not published")
    
    # Verify student is enrolled in the exam's class
    class_ids = StudentService.get_student_classes(db, current_user.id)
    if exam.class_id not in class_ids:
        raise HTTPException(status_code=403, detail="You are not enrolled in this exam's class")
    
    # Verify exam is within date range
    # For Pakistan timezone (UTC+5), adjust exam times for comparison
    now = datetime.now(timezone.utc)
    PAKISTAN_OFFSET = timedelta(hours=5)
    
    if exam.start_date:
        # Compare: (exam UTC - 5 hours) with current UTC
        exam_start_pakistan = exam.start_date - PAKISTAN_OFFSET
        if exam_start_pakistan > now:
            raise HTTPException(status_code=403, detail="Exam has not started yet")
    
    if exam.end_date:
        exam_end_pakistan = exam.end_date - PAKISTAN_OFFSET
        if exam_end_pakistan < now:
            raise HTTPException(status_code=403, detail="Exam has ended")
    
    # Get or create attempt
    attempt = db.query(ExamAttempt).filter(
        and_(
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == current_user.id,
            ExamAttempt.status == ExamAttemptStatus.IN_PROGRESS.value
        )
    ).order_by(ExamAttempt.started_at.desc()).first()
    
    # Load questions without correct answers
    questions = db.query(Question).filter(Question.exam_id == exam_id).order_by(Question.order_number).all()
    question_list = []
    
    for question in questions:
        question_dict = {
            "id": str(question.id),
            "question_text": question.question_text,
            "question_type": question.question_type,
            "difficulty_level": question.difficulty_level,
            "points": float(question.points),
            "order_number": question.order_number,
        }
        
        # Add options but hide correct answer
        if question.question_type in [QuestionType.MCQ.value, QuestionType.TRUE_FALSE.value]:
            options = db.query(QuestionOption).filter(QuestionOption.question_id == question.id).order_by(QuestionOption.order_number).all()
            question_dict["options"] = [
                {
                    "id": str(opt.id),
                    "option_text": opt.option_text,
                    "order_number": opt.order_number
                }
                for opt in options
            ]
        
        question_list.append(question_dict)
    
    exam_data = ExamResponseSchema.model_validate(exam).model_dump()
    # Convert dates to UTC Z format using helper function
    from app.services.student_service import to_utc_z
    if exam.start_date:
        exam_data["start_date"] = to_utc_z(exam.start_date)
    if exam.end_date:
        exam_data["end_date"] = to_utc_z(exam.end_date)
    exam_data["questions"] = question_list
    exam_data["attempt"] = {
        "id": str(attempt.id),
        "started_at": attempt.started_at.isoformat().replace("+00:00", "Z") if attempt.started_at else None,
        "status": attempt.status
    } if attempt else None
    
    return exam_data


@router.post("/exams/{exam_id}/start", response_model=ExamAttemptResponse)
async def start_exam(
    exam_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Start a new exam attempt."""
    # Verify exam exists and is published
    exam = ExamService.get_exam(db, exam_id)
    
    if not exam.is_published:
        raise HTTPException(status_code=403, detail="Exam is not published")
    
    # Verify student is enrolled
    class_ids = StudentService.get_student_classes(db, current_user.id)
    if exam.class_id not in class_ids:
        raise HTTPException(status_code=403, detail="You are not enrolled in this exam's class")
    
    # Verify exam is within date range
    # For Pakistan timezone (UTC+5), adjust exam times for comparison
    now = datetime.now(timezone.utc)
    PAKISTAN_OFFSET = timedelta(hours=5)
    
    if exam.start_date:
        # Compare: (exam UTC - 5 hours) with current UTC
        exam_start_pakistan = exam.start_date - PAKISTAN_OFFSET
        if exam_start_pakistan > now:
            raise HTTPException(status_code=403, detail="Exam has not started yet")
    
    if exam.end_date:
        exam_end_pakistan = exam.end_date - PAKISTAN_OFFSET
        if exam_end_pakistan < now:
            raise HTTPException(status_code=403, detail="Exam has ended")
    
    # Check existing attempts
    existing_attempts = db.query(ExamAttempt).filter(
        and_(
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == current_user.id
        )
    ).all()
    
    # Check if there's an in-progress attempt
    in_progress = [a for a in existing_attempts if a.status == ExamAttemptStatus.IN_PROGRESS.value]
    if in_progress:
        return ExamAttemptResponse.model_validate(in_progress[0])
    
    # Check max attempts
    submitted_count = len([a for a in existing_attempts if a.status == ExamAttemptStatus.SUBMITTED.value])
    if submitted_count >= exam.max_attempts and not exam.allow_retake:
        raise HTTPException(status_code=403, detail="Maximum attempts reached")
    
    # Create new attempt
    attempt_number = len(existing_attempts) + 1
    attempt = ExamAttempt(
        exam_id=exam_id,
        student_id=current_user.id,
        status=ExamAttemptStatus.IN_PROGRESS.value,
        attempt_number=attempt_number
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    
    return ExamAttemptResponse.model_validate(attempt)


@router.get("/exams/{exam_id}/attempts/{attempt_id}", response_model=ExamAttemptResponse)
async def get_attempt(
    exam_id: UUID,
    attempt_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Get exam attempt details."""
    attempt = db.query(ExamAttempt).filter(
        and_(
            ExamAttempt.id == attempt_id,
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == current_user.id
        )
    ).first()
    
    if not attempt:
        raise NotFoundError("Attempt not found")
    
    # Load responses
    responses = db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt_id).all()
    attempt_dict = ExamAttemptResponse.model_validate(attempt).model_dump()
    attempt_dict["responses"] = [
        {
            "question_id": str(r.question_id),
            "answer_text": r.answer_text,
            "selected_options": [str(opt) for opt in (r.selected_options or [])] if r.selected_options else None
        }
        for r in responses
    ]
    
    return attempt_dict


@router.put("/exams/{exam_id}/attempts/{attempt_id}/responses", response_model=MessageResponse)
async def update_attempt_responses(
    exam_id: UUID,
    attempt_id: UUID,
    responses_data: dict,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Update exam attempt responses (auto-save)."""
    attempt = db.query(ExamAttempt).filter(
        and_(
            ExamAttempt.id == attempt_id,
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == current_user.id,
            ExamAttempt.status == ExamAttemptStatus.IN_PROGRESS.value
        )
    ).first()
    
    if not attempt:
        raise NotFoundError("Attempt not found or already submitted")
    
    responses = responses_data.get("responses", [])
    
    for response_data in responses:
        question_id = UUID(response_data["question_id"])
        
        # Check if response exists
        existing = db.query(ExamResponse).filter(
            and_(
                ExamResponse.attempt_id == attempt_id,
                ExamResponse.question_id == question_id
            )
        ).first()
        
        if existing:
            # Update existing
            existing.answer_text = response_data.get("answer_text")
            existing.selected_options = [UUID(opt) for opt in response_data.get("selected_options", [])] if response_data.get("selected_options") else None
        else:
            # Create new
            response = ExamResponse(
                attempt_id=attempt_id,
                question_id=question_id,
                answer_text=response_data.get("answer_text"),
                selected_options=[UUID(opt) for opt in response_data.get("selected_options", [])] if response_data.get("selected_options") else None
            )
            db.add(response)
    
    db.commit()
    return MessageResponse(message="Responses saved")


@router.post("/exams/{exam_id}/attempts/{attempt_id}/submit", response_model=ExamResultResponse)
async def submit_exam(
    exam_id: UUID,
    attempt_id: UUID,
    submit_data: ExamSubmit,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Submit exam attempt and calculate results."""
    try:
        attempt = db.query(ExamAttempt).filter(
            and_(
                ExamAttempt.id == attempt_id,
                ExamAttempt.exam_id == exam_id,
                ExamAttempt.student_id == current_user.id
            )
        ).first()
        
        if not attempt:
            raise HTTPException(status_code=404, detail="Attempt not found")
        
        # Check if already submitted - if so, return existing result
        if attempt.status == ExamAttemptStatus.SUBMITTED.value:
            existing_result = db.query(ExamResult).filter(ExamResult.attempt_id == attempt_id).first()
            if existing_result:
                return ExamResultResponse.model_validate(existing_result)
            else:
                # Status is submitted but no result - this shouldn't happen, but handle it
                raise HTTPException(status_code=400, detail="Exam already submitted but result not found")
        
        # Verify attempt is in progress
        if attempt.status != ExamAttemptStatus.IN_PROGRESS.value:
            raise HTTPException(status_code=400, detail=f"Attempt is not in progress (status: {attempt.status})")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error finding attempt: {e}")
        raise HTTPException(status_code=500, detail=f"Error finding attempt: {str(e)}")
    
    # Update attempt status
    attempt.status = ExamAttemptStatus.SUBMITTED.value
    attempt.submitted_at = datetime.now(timezone.utc)
    
    # Calculate time spent
    if attempt.started_at:
        time_diff = (attempt.submitted_at - attempt.started_at).total_seconds() / 60
        attempt.time_spent_minutes = int(time_diff)
    
    # Save responses first (with correctness calculation)
    for response_data in submit_data.responses:
        try:
            # Convert question_id to UUID (handle both string and UUID formats)
            if isinstance(response_data.question_id, str):
                question_id = UUID(response_data.question_id)
            else:
                question_id = response_data.question_id
            
            question = db.query(Question).filter(Question.id == question_id).first()
            
            if not question:
                print(f"Warning: Question {question_id} not found, skipping")
                continue
        except (ValueError, TypeError) as e:
            print(f"Error processing response: Invalid question_id {response_data.question_id}: {e}")
            continue
        
        # Check if response exists
        existing = db.query(ExamResponse).filter(
            and_(
                ExamResponse.attempt_id == attempt_id,
                ExamResponse.question_id == question_id
            )
        ).first()
        
        if existing:
            response = existing
        else:
            response = ExamResponse(
                attempt_id=attempt_id,
                question_id=question_id
            )
            db.add(response)
        
        # Update response
        response.answer_text = response_data.answer_text
        
        # Convert selected_options from strings to UUIDs for ARRAY(UUID) column
        if response_data.selected_options and len(response_data.selected_options) > 0:
            try:
                # Convert each option to UUID
                uuid_options = []
                for opt in response_data.selected_options:
                    if isinstance(opt, str):
                        uuid_options.append(UUID(opt))
                    elif isinstance(opt, UUID):
                        uuid_options.append(opt)
                    else:
                        print(f"Warning: Invalid option format: {opt}, skipping")
                response.selected_options = uuid_options if uuid_options else None
            except (ValueError, TypeError) as e:
                # If conversion fails, log and set to None
                print(f"Error converting selected_options to UUIDs: {e}, options: {response_data.selected_options}")
                response.selected_options = None
        else:
            response.selected_options = None
        
        # Check correctness - only for MCQ and True/False questions
        if question.question_type in [QuestionType.MCQ.value, QuestionType.TRUE_FALSE.value]:
            # Get correct options
            correct_options = db.query(QuestionOption).filter(
                and_(
                    QuestionOption.question_id == question_id,
                    QuestionOption.is_correct == True
                )
            ).all()
            correct_ids = {str(opt.id) for opt in correct_options}
            # Convert selected_options (UUIDs) to strings for comparison
            selected_ids = {str(opt) for opt in (response.selected_options or [])}
            
            # Debug logging
            print(f"Question {question_id}: correct_ids={correct_ids}, selected_ids={selected_ids}")
            
            # Check if selected options match correct options exactly
            if len(correct_ids) > 0:
                # Both sets must be equal (order doesn't matter, but all correct must be selected and no extras)
                is_correct = (correct_ids == selected_ids)
                if not is_correct:
                    print(f"Question {question_id}: Mismatch - correct={sorted(correct_ids)}, selected={sorted(selected_ids)}")
            else:
                # No correct options marked - this shouldn't happen, but handle it
                print(f"Warning: Question {question_id} has no correct options marked")
                is_correct = False
        else:
            # For text answers, mark as needing review (is_correct = None)
            is_correct = None
        
        response.is_correct = is_correct
        if is_correct:
            response.points_earned = question.points
        elif is_correct is False:
            response.points_earned = 0
        else:
            # Needs review, give 0 for now
            response.points_earned = 0
    
    try:
        db.commit()
        print(f"Successfully saved {len(submit_data.responses)} responses to exam_responses table")
    except Exception as e:
        db.rollback()
        print(f"Error committing responses: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error saving responses: {str(e)}")
    
    # NOW calculate result from exam_responses table and save to exam_results table
    print(f"Calling calculate_and_save_result for exam_id={exam_id}, attempt_id={attempt_id}")
    try:
        result = calculate_and_save_result(db, exam_id, attempt_id)
        print(f"Result calculated and saved successfully: {result.total_score}/{result.max_score} = {result.percentage}%")
        return ExamResultResponse.model_validate(result)
    except Exception as e:
        print(f"Error in calculate_and_save_result: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error calculating result: {str(e)}")


@router.post("/exams/{exam_id}/attempts/{attempt_id}/recalculate", response_model=ExamResultResponse)
async def recalculate_result(
    exam_id: UUID,
    attempt_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Recalculate exam result from exam_responses table."""
    # Verify attempt belongs to current user
    attempt = db.query(ExamAttempt).filter(
        and_(
            ExamAttempt.id == attempt_id,
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == current_user.id,
            ExamAttempt.status == ExamAttemptStatus.SUBMITTED.value
        )
    ).first()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found or not submitted")
    
    # Calculate result from exam_responses table and save to exam_results table
    result = calculate_and_save_result(db, exam_id, attempt_id)
    return ExamResultResponse.model_validate(result)


@router.get("/exams/{exam_id}/attempts/{attempt_id}/responses", response_model=dict)
async def get_attempt_responses(
    exam_id: UUID,
    attempt_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Get all responses for an attempt (for debugging/verification)."""
    # Verify attempt belongs to current user
    attempt = db.query(ExamAttempt).filter(
        and_(
            ExamAttempt.id == attempt_id,
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == current_user.id
        )
    ).first()
    
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # Get all responses from database
    responses = db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt_id).all()
    
    # Get questions for context
    questions = db.query(Question).filter(Question.exam_id == exam_id).all()
    question_map = {q.id: q for q in questions}
    
    response_list = []
    for response in responses:
        question = question_map.get(response.question_id)
        response_list.append({
            "id": str(response.id),
            "question_id": str(response.question_id),
            "question_text": question.question_text if question else "Question not found",
            "answer_text": response.answer_text,
            "selected_options": [str(opt) for opt in (response.selected_options or [])] if response.selected_options else None,
            "is_correct": response.is_correct,
            "points_earned": float(response.points_earned) if response.points_earned else 0,
            "answered_at": response.answered_at.isoformat() if response.answered_at else None
        })
    
    # Calculate summary
    total_responses = len(responses)
    correct_count = sum(1 for r in responses if r.is_correct is True)
    incorrect_count = sum(1 for r in responses if r.is_correct is False)
    needs_review = sum(1 for r in responses if r.is_correct is None)
    total_points = sum(float(r.points_earned or 0) for r in responses)
    max_points = sum(float(q.points) for q in questions)
    
    return {
        "attempt_id": str(attempt_id),
        "total_responses": total_responses,
        "correct_count": correct_count,
        "incorrect_count": incorrect_count,
        "needs_review": needs_review,
        "total_points_earned": total_points,
        "max_points": max_points,
        "percentage": (total_points / max_points * 100) if max_points > 0 else 0,
        "responses": response_list
    }


@router.get("/materials", response_model=PaginatedResponse[MaterialResponse])
async def list_materials(
    class_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """List materials available to student."""
    result = StudentService.get_student_materials(
        db, current_user.id, class_id, page, limit
    )
    return PaginatedResponse(
        items=[MaterialResponse.model_validate(m) for m in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.get("/materials/{material_id}", response_model=MaterialResponse)
async def get_material(
    material_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Get material details."""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise NotFoundError("Material not found")
    
    # Verify student has access (enrolled in material's class)
    class_ids = StudentService.get_student_classes(db, current_user.id)
    if material.class_id not in class_ids:
        raise HTTPException(status_code=403, detail="You don't have access to this material")
    
    return MaterialResponse.model_validate(material)


@router.get("/materials/{material_id}/view")
async def view_material(
    material_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """View a material file inline (opens in browser instead of downloading)."""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise NotFoundError("Material not found")
    
    # Verify student has access
    class_ids = StudentService.get_student_classes(db, current_user.id)
    if material.class_id not in class_ids:
        raise HTTPException(status_code=403, detail="You don't have access to this material")
    
    # Determine media type based on file extension
    file_ext = Path(material.file_name or '').suffix.lower()
    media_types = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.txt': 'text/plain',
        '.html': 'text/html',
        '.xml': 'application/xml',
    }
    media_type = media_types.get(file_ext, 'application/octet-stream')

    # Cloudinary-hosted file: proxy the bytes so auth stays enforced
    if material.file_url.startswith("http"):
        try:
            file_bytes = StorageService.fetch_file(material.file_url)
        except Exception:
            raise NotFoundError("File not found in storage")
        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={
                'Content-Disposition': f'inline; filename="{material.file_name}"'
            }
        )

    # Legacy local file (pre-Cloudinary uploads)
    file_path = Path(material.file_url)
    if not file_path.is_absolute():
        backend_root = Path(__file__).parent.parent.parent.parent
        file_path = backend_root / file_path

    if not file_path.exists():
        raise NotFoundError("File not found")

    return FileResponse(
        str(file_path),
        filename=material.file_name,
        media_type=media_type,
        headers={
            'Content-Disposition': f'inline; filename="{material.file_name}"'
        }
    )


@router.get("/materials/{material_id}/download")
async def download_material(
    material_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Download a material file."""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise NotFoundError("Material not found")
    
    # Verify student has access
    class_ids = StudentService.get_student_classes(db, current_user.id)
    if material.class_id not in class_ids:
        raise HTTPException(status_code=403, detail="You don't have access to this material")
    
    # Cloudinary-hosted file: proxy the bytes so auth stays enforced
    if material.file_url.startswith("http"):
        try:
            file_bytes = StorageService.fetch_file(material.file_url)
        except Exception:
            raise NotFoundError("File not found in storage")
        return Response(
            content=file_bytes,
            media_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{material.file_name}"'}
        )

    # Legacy local file (pre-Cloudinary uploads)
    file_path = Path(material.file_url)
    if not file_path.is_absolute():
        backend_root = Path(__file__).parent.parent.parent.parent
        file_path = backend_root / file_path

    if not file_path.exists():
        raise NotFoundError("File not found")

    return FileResponse(
        str(file_path),
        filename=material.file_name,
        media_type='application/octet-stream'
    )


@router.get("/results", response_model=PaginatedResponse)
async def list_results(
    exam_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """List exam results for student."""
    query = db.query(ExamResult).join(ExamAttempt).filter(
        ExamAttempt.student_id == current_user.id
    )
    
    if exam_id:
        query = query.filter(ExamAttempt.exam_id == exam_id)
    
    total = query.count()
    results = query.order_by(ExamResult.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    
    # Get exam details for each result
    result_list = []
    for result in results:
        attempt = db.query(ExamAttempt).filter(ExamAttempt.id == result.attempt_id).first()
        exam = db.query(Exam).filter(Exam.id == attempt.exam_id).first()
        
        result_list.append({
            "id": str(result.id),
            "exam_id": str(exam.id),
            "exam_name": exam.title,
            "total_score": float(result.total_score),
            "max_score": float(result.max_score),
            "percentage": float(result.percentage),
            "grade": result.grade,
            "passed": result.passed,
            "created_at": result.created_at.isoformat() if result.created_at else None,
            "exam": {
                "id": str(exam.id),
                "title": exam.title,
                "description": exam.description
            },
            "attempt": {
                "id": str(attempt.id),
                "started_at": attempt.started_at.isoformat().replace("+00:00", "Z") if attempt.started_at else None,
                "submitted_at": attempt.submitted_at.isoformat().replace("+00:00", "Z") if attempt.submitted_at else None,
                "time_spent_minutes": attempt.time_spent_minutes
            }
        })
    
    return PaginatedResponse(
        items=result_list,
        total=total,
        page=page,
        limit=limit,
        pages=(total + limit - 1) // limit
    )


@router.get("/results/{result_id}", response_model=dict)
async def get_result(
    result_id: UUID,
    current_user: User = Depends(get_student_user),
    db: Session = Depends(get_db)
):
    """Get exam result details with exam info and responses."""
    result = db.query(ExamResult).join(ExamAttempt).filter(
        and_(
            ExamResult.id == result_id,
            ExamAttempt.student_id == current_user.id
        )
    ).first()
    
    if not result:
        raise NotFoundError("Result not found")
    
    # Get attempt and exam details
    attempt = db.query(ExamAttempt).filter(ExamAttempt.id == result.attempt_id).first()
    if not attempt:
        raise NotFoundError("Attempt not found")
    
    exam = db.query(Exam).filter(Exam.id == attempt.exam_id).first()
    if not exam:
        raise NotFoundError("Exam not found")
    
    # Get all responses for this attempt
    responses = db.query(ExamResponse).filter(ExamResponse.attempt_id == result.attempt_id).all()
    
    # Get questions with options for display
    questions = db.query(Question).filter(Question.exam_id == exam.id).order_by(Question.order_number).all()
    question_responses = []
    
    for question in questions:
        # Find response for this question
        question_response = next((r for r in responses if r.question_id == question.id), None)
        
        # Get options
        options = None
        if question.question_type in [QuestionType.MCQ.value, QuestionType.TRUE_FALSE.value]:
            options = db.query(QuestionOption).filter(QuestionOption.question_id == question.id).order_by(QuestionOption.order_number).all()
            options = [
                {
                    "id": str(opt.id),
                    "option_text": opt.option_text,
                    "is_correct": opt.is_correct,
                    "order_number": opt.order_number
                }
                for opt in options
            ]
        
        question_responses.append({
            "id": str(question.id),
            "question_text": question.question_text,
            "question_type": question.question_type,
            "difficulty_level": question.difficulty_level,
            "points": float(question.points),
            "order_number": question.order_number,
            "options": options,
            "response": {
                "answer_text": question_response.answer_text if question_response else None,
                "selected_options": [str(opt) for opt in (question_response.selected_options or [])] if question_response and question_response.selected_options else None,
                "is_correct": question_response.is_correct if question_response else None,
                "points_earned": float(question_response.points_earned) if question_response and question_response.points_earned else 0
            } if question_response else None
        })
    
    # Build response
    result_data = ExamResultResponse.model_validate(result).model_dump()
    result_data["exam"] = {
        "id": str(exam.id),
        "title": exam.title,
        "description": exam.description
    }
    result_data["attempt"] = {
        "id": str(attempt.id),
        "started_at": attempt.started_at.isoformat().replace("+00:00", "Z") if attempt.started_at else None,
        "submitted_at": attempt.submitted_at.isoformat().replace("+00:00", "Z") if attempt.submitted_at else None,
        "time_spent_minutes": attempt.time_spent_minutes
    }
    result_data["questions"] = question_responses
    
    return result_data
