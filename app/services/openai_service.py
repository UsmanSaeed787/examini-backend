from typing import List, Dict
from openai import OpenAI
from app.config import settings
from app.models.material import Material
import json


class OpenAIService:
    """Service for OpenAI integration."""
    
    def __init__(self):
        if settings.openai_api_key:
            # Gemini models are served via Google's OpenAI-compatible endpoint
            # (chat completions); any other model name uses the default OpenAI base URL.
            base_url = (
                "https://generativelanguage.googleapis.com/v1beta/openai/"
                if settings.openai_model.lower().startswith("gemini")
                else None
            )
            self.client = OpenAI(api_key=settings.openai_api_key, base_url=base_url)
            self.model = settings.openai_model
        else:
            self.client = None
    
    async def generate_exam_from_materials(
        self,
        materials: List[str],
        question_config: Dict
    ) -> List[Dict]:
        """Generate exam questions from materials using OpenAI."""
        if not self.client:
            raise ValueError("OpenAI API key not configured")
        
        # Build prompt
        material_text = "\n\n".join(materials)
        
        prompt = f"""Generate an exam based on the following material:

{material_text}

Requirements:
- Total questions: {question_config.get('total', 10)}
- Easy questions: {question_config.get('easy', 0)}
- Medium questions: {question_config.get('medium', 0)}
- Hard questions: {question_config.get('hard', 0)}
- MCQ questions: {question_config.get('mcq', 0)}
- Short answer questions: {question_config.get('short_answer', 0)}
- Long answer questions: {question_config.get('long_answer', 0)}

For each question, provide:
1. question_text: The question
2. question_type: One of 'mcq', 'short_answer', 'long_answer', 'true_false'
3. difficulty_level: One of 'easy', 'medium', 'hard'
4. points: Points for this question (default 1.0)
5. For MCQ: options array with option_text and is_correct flag

Return the response as a JSON array of questions. Format:
[
  {{
    "question_text": "...",
    "question_type": "mcq",
    "difficulty_level": "easy",
    "points": 1.0,
    "order_number": 1,
    "options": [
      {{"option_text": "...", "is_correct": true, "order_number": 1}},
      {{"option_text": "...", "is_correct": false, "order_number": 2}}
    ]
  }}
]
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert exam question generator. Generate high-quality exam questions based on provided material."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            parsed = json.loads(content)
            
            # Handle both array and object with questions key
            if isinstance(parsed, list):
                questions = parsed
            elif "questions" in parsed:
                questions = parsed["questions"]
            else:
                questions = [parsed]
            
            # Add order_number if missing
            for idx, question in enumerate(questions, 1):
                if "order_number" not in question:
                    question["order_number"] = idx
            
            return questions
            
        except Exception as e:
            raise ValueError(f"Failed to generate exam: {str(e)}")
    
    @staticmethod
    def parse_material_file(material: Material) -> str:
        """Extract the material's real text; header lets the LLM tell materials apart."""
        from app.services.parser_service import ParserService
        text = ParserService.extract_text(material)
        return f"=== Material: {material.title} ===\n{text}"

