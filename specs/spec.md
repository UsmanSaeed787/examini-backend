# SPEC — Real Material Text Extraction for AI Exam Generation

## 1. Problem

`OpenAIService.parse_material_file()` ([openai_service.py](backend/app/services/openai_service.py)) is a stub:

```python
return f"Material content from {material.file_name}"
```

So when a teacher clicks **Generate with AI**, Gemini receives only the *filename* (e.g. `Chapter1-da-gop-1.pdf`) — not the chapter's text. The generated questions are generic, not based on the uploaded material. This spec defines the real implementation.

## 2. Goal

When a teacher selects materials and generates an exam, the backend must:
1. Fetch each selected material's file bytes (from Cloudinary, or legacy local disk).
2. Extract its actual text (PDF, DOCX, TXT).
3. Feed that text to Gemini so questions come from the material's content.

Out of scope: OCR for scanned/image PDFs, parsing images (png/jpg), legacy `.doc` (binary Word 97) support, any frontend changes, any database changes.

## 3. New Dependencies

| Package | Purpose | Notes |
|---|---|---|
| `pypdf` | PDF text extraction | Pure-Python, no system deps, maintained successor of PyPDF2 |
| `python-docx` | DOCX text extraction | Paragraphs + tables |

Added to `pyproject.toml` and `requirements.txt`. TXT needs no library (bytes decode).

## 4. Design

### 4.1 New service: `backend/app/services/parser_service.py`

One public entry point:

```python
class ParserService:
    @staticmethod
    def extract_text(material: Material) -> str:
        """Fetch the material's file and return its plain text.
        Raises ValueError with a human-readable message on any failure."""
```

Internal steps:

1. **Fetch bytes**
   - `file_url` starts with `http` → `StorageService.fetch_file(url)` (Cloudinary — already implemented).
   - Otherwise → read from disk (legacy pre-Cloudinary uploads), resolving relative paths from the backend root exactly like the download endpoints do.
2. **Dispatch by type** — use `material.file_type` (stored at upload), falling back to the `file_name` extension:
   - `pdf` → `pypdf.PdfReader`; join `page.extract_text()` for all pages.
   - `docx` → `python-docx`; join all paragraph texts, plus table cell texts (row cells joined with ` | `).
   - `txt` → decode bytes as UTF-8; on failure retry `latin-1` (never crashes).
   - `doc`, `png`, `jpg`, `jpeg`, anything else → raise `ValueError("File type '<ext>' is not supported for AI generation (supported: pdf, docx, txt)")`.
3. **Validate output** — if extracted text (stripped) is **< 50 characters**, raise `ValueError("No readable text found in '<file_name>' — it may be a scanned/image-only PDF")`. This catches scanned PDFs, which extract as empty text.
4. **Cap length** — truncate each material's text to **`MAX_CHARS_PER_MATERIAL = 60_000`** characters (≈15k tokens), appending `"\n[... truncated]"` when cut. Gemini Flash's context is large, but the cap keeps requests fast, cheap, and safe against 500-page uploads.

### 4.2 Changes to existing code (2 small edits)

**`openai_service.py`** — `parse_material_file()` keeps its name and signature (so the route's call site logic is untouched) but delegates:

```python
@staticmethod
def parse_material_file(material: Material) -> str:
    text = ParserService.extract_text(material)
    return f"=== Material: {material.title} ===\n{text}"
```

The `=== Material: <title> ===` header means that when several materials are selected, Gemini sees where each one starts (the prompt already joins them with blank lines).

**`routes/teacher.py`** — in `generate_exam`, wrap the parsing loop so a bad material returns a clear **400** instead of a generic 500:

```python
try:
    materials_text = [OpenAIService.parse_material_file(m) for m in materials]
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

The frontend already displays `detail` in its error toast — no frontend change needed.

### 4.3 Error behavior (decided, please review)

- **One selected material fails ⇒ the whole generation fails** with a message naming the file. Rationale: silently generating from a subset would misrepresent what the exam covers; the teacher can deselect the bad file and retry. *(Alternative — skip bad files with a warning — rejected for silent-wrong-result risk.)*
- Upload validation is unchanged: teachers can still upload png/jpg as *study materials* (students view/download them); they just can't be used as AI generation sources.

## 5. Files Touched

| File | Change |
|---|---|
| `backend/app/services/parser_service.py` | **new** — fetch + extract + validate + cap |
| `backend/app/services/openai_service.py` | stub body replaced with delegation + title header |
| `backend/app/api/routes/teacher.py` | wrap parse loop → HTTP 400 with message |
| `backend/pyproject.toml`, `requirements.txt` | add `pypdf`, `python-docx` |

No schema, no migration, no frontend, no `.env` changes.

## 6. Acceptance Tests (run before declaring done)

1. **Unit-level, real file:** extract text from one of the real PDFs in `backend/app/uploads/` — printed excerpt must contain actual sentence text from the document, length > 200 chars.
2. **TXT + DOCX:** generate a small `.txt` and `.docx` locally, extract, verify contents round-trip.
3. **Failure cases:** an image file and an empty PDF must raise the specified `ValueError` messages (not crash).
4. **End-to-end with Gemini:** parse a real PDF → `generate_exam_from_materials` with a 2-question config → questions returned must reference the document's actual subject matter (manual sanity check of question text).
5. **App still boots:** `from app.main import app` imports clean.

## 7. Known Limitations (accepted)

- Scanned/image-only PDFs are rejected with a clear message (no OCR — would need heavy deps like Tesseract; can be a future enhancement).
- Legacy `.doc` (Word 97 binary) is rejected — users should re-save as `.docx`.
- PDF extraction quality depends on the PDF's internal structure (multi-column layouts may interleave text); acceptable for exam-generation purposes.
- The 60k-char cap means extremely long books are partially used (first ~30–40 pages of dense text per material). Teachers can split materials per chapter — which is already the natural usage pattern.
