# UPDATE.md — Examini Stack Migration & Deployment Plan

This document defines the complete migration of Examini away from Supabase to a fully free stack, plus the deployment setup. It covers **what changes, why, and exactly which code to touch**.

## New Stack Overview

| Concern | Old | New | Cost |
|---|---|---|---|
| Database | Supabase PostgreSQL (project got auto-paused & deleted) | **Neon** (serverless PostgreSQL, auto-wakes on connection) | Free |
| File storage | Local disk (`backend/uploads/`) | **Cloudinary** (needed because Render's disk is ephemeral) | Free tier |
| AI exam generation | OpenAI (`gpt-4o-mini`, paid) | **Gemini API** via its OpenAI-compatible endpoint | Free tier |
| Backend hosting | — (local only) | **Render** (free web service) | Free (sleeps when idle) |
| Frontend hosting | — (local only) | **Vercel** | Free |
| Google login | Google OAuth | Google OAuth (unchanged, just configured) | Free |

Key insight that makes this easy: **the backend never actually calls Supabase APIs.** The `supabase` client is never imported anywhere in `app/` — only three unused settings in `config.py` reference it. The app is plain SQLAlchemy + PostgreSQL, local-disk files, and its own JWT auth. So the "migration" is mostly configuration, plus one real code task (Cloudinary).

---

## 1. Database → Neon

### 1.1 Setup (no code)

1. Create a free project at [neon.tech](https://neon.tech) → copy the **connection string** (`postgresql://...@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`).
2. Set it as `DATABASE_URL` in `backend/.env`.
3. Run the migrations in Neon's **SQL Editor**, in order:
   - `01_create_extensions.sql`
   - `02_create_tables.sql`
   - `03_create_indexes.sql`
   - `04_create_functions_triggers.sql`
   - **SKIP `05_setup_rls_policies.sql`** — it uses `auth.uid()`, a Supabase-only function; it will error on Neon. Safe to skip: RLS is not used for enforcement anywhere (all access control is in FastAPI).
   - `06_seed_initial_data.sql` — **first replace the placeholder hash.** Generate a real one:
     ```powershell
     cd backend
     uv run python -c "from app.utils.security import get_password_hash; print(get_password_hash('Admin@123'))"
     ```
     Paste the output over `'$2b$12$PLACEHOLDER_HASH_HERE_REPLACE_WITH_ACTUAL_BCRYPT_HASH'`, then run it. Admin login = `admin@examini.com` / `Admin@123`.
   - `07_add_student_profiles_and_roll_numbers.sql`

### 1.2 Code changes (remove Supabase requirement)

**`backend/app/config.py`** — the three Supabase settings are currently *required*, forcing dummy values in `.env`. Make them optional:

```python
# Database
database_url: str

# Supabase (legacy — no longer used, kept optional for backward compat)
supabase_url: str = ""
supabase_key: str = ""
supabase_service_role_key: str = ""
```

**`backend/pyproject.toml`** — remove the unused dependency line `"supabase>=2.3.0",` and run `uv sync`. (Also removable from `requirements.txt`.)

**`backend/.env`** — after the config change, delete the `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` lines entirely.

---

## 2. File Storage → Cloudinary

**Why required, not optional:** Render's free tier has an **ephemeral filesystem** — files written to `backend/uploads/` are wiped on every deploy/restart. Materials must live in external storage.

### 2.1 Setup

1. Create a free account at [cloudinary.com](https://cloudinary.com) → Dashboard shows **Cloud name**, **API Key**, **API Secret**.
2. PDFs: in Cloudinary **Settings → Security**, ensure "PDF and ZIP files delivery" is allowed (new free accounts sometimes have it off).
3. Add to `backend/.env`:
   ```env
   CLOUDINARY_CLOUD_NAME=your_cloud_name
   CLOUDINARY_API_KEY=your_api_key
   CLOUDINARY_API_SECRET=your_api_secret
   ```

### 2.2 Code changes

**`backend/pyproject.toml`** — add `"cloudinary>=1.40.0",` then `uv sync`.

**`backend/app/config.py`** — add settings:
```python
# Cloudinary
cloudinary_cloud_name: str = ""
cloudinary_api_key: str = ""
cloudinary_api_secret: str = ""
```

**New file `backend/app/services/storage_service.py`** — one place for all storage logic:
```python
import cloudinary
import cloudinary.uploader
import httpx
from app.config import settings

cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
    secure=True,
)


class StorageService:
    @staticmethod
    def upload_file(content: bytes, public_id: str) -> str:
        """Upload raw bytes; returns the permanent https URL."""
        result = cloudinary.uploader.upload(
            content,
            resource_type="raw",          # raw = any file type (pdf, docx, txt, ...)
            public_id=f"examini/materials/{public_id}",
            overwrite=False,
        )
        return result["secure_url"]

    @staticmethod
    def fetch_file(url: str) -> bytes:
        """Fetch file bytes back from Cloudinary (for authenticated proxy downloads)."""
        response = httpx.get(url, timeout=60)
        response.raise_for_status()
        return response.content
```
(`httpx` is already a project dependency.)

**`backend/app/api/routes/teacher.py` — `upload_material` (currently lines ~297–345):** replace the local-disk block. Delete the `backend_root` / `upload_path.mkdir` / `open(file_path, 'wb')` section and replace with:

```python
from app.services.storage_service import StorageService

# after the existing extension + size validation (keep that as-is):
safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename or 'file')
file_id = str(uuid4())
try:
    file_url = StorageService.upload_file(content, f"{file_id}_{safe_filename}")
except Exception as e:
    raise HTTPException(status_code=500, detail="Failed to upload file to storage")

material = MaterialService.create_material(
    db, material_data, current_user.id,
    file_url=file_url,                 # now an https URL, not a disk path
    file_name=file.filename,
    file_type=file_ext,
    file_size=len(content),
)
```
The `file_url` DB column needs no schema change — it now stores a URL instead of a path (this also fixes the old quirk of leaking absolute server paths to clients). The "delete file if DB save fails" fallback can be dropped or replaced with `cloudinary.uploader.destroy(...)`.

**Downloads/views — 3 endpoints stream from URL instead of disk.** Keep the endpoints (they enforce auth/enrollment and the frontend already calls them expecting blobs — zero frontend changes needed); just swap `FileResponse` for a proxied response:

- `teacher.py` → `download_material` (~line 372)
- `student.py` → `view_material` (~line 769) and `download_material` (~line 830)

Pattern (replace the `Path(...)`/`file_path.exists()`/`FileResponse` block in each):
```python
from fastapi.responses import Response
from app.services.storage_service import StorageService

try:
    file_bytes = StorageService.fetch_file(material.file_url)
except Exception:
    raise HTTPException(status_code=404, detail="File not found in storage")

return Response(
    content=file_bytes,
    media_type=media_type,   # keep each endpoint's existing media-type logic
    headers={"Content-Disposition": f'{disposition}; filename="{material.file_name}"'},
    # disposition = "inline" for the student view endpoint, "attachment" for downloads
)
```

**Delete:** material deletion is a soft delete (`is_active=False`) — no Cloudinary change required. (Optional cleanup: call `cloudinary.uploader.destroy` on hard-delete, deriving the public_id from the URL.)

**Old files:** anything in `backend/app/uploads/` from before won't migrate automatically — re-upload materials through the UI after switching.

---

## 3. AI Generation → Gemini API

Gemini exposes an **OpenAI-compatible endpoint**, and the backend already uses the OpenAI SDK — so this is a 2-line change.

1. Get a free API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. **`backend/app/services/openai_service.py`** — in `__init__`, add `base_url`:
   ```python
   self.client = OpenAI(
       api_key=settings.openai_api_key,
       base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
   )
   ```
3. **`backend/.env`**:
   ```env
   OPENAI_API_KEY=<your Gemini API key>
   OPENAI_MODEL=gemini-2.5-flash
   ```

Everything else (JSON response format, prompt, parsing) works unchanged.

> ⚠️ Known pre-existing limitation (unchanged by this migration): `parse_material_file()` is a stub — the AI receives only material *filenames*, not the file text. Real PDF/text extraction is a separate future task; switching to Gemini doesn't fix or worsen it.

---

## 4. Google OAuth

Free; console setup only, no code changes.

1. [console.cloud.google.com](https://console.cloud.google.com) → create project → **APIs & Services → OAuth consent screen** → External → fill app name + support email.
2. **Credentials → Create Credentials → OAuth client ID → Web application.**
   - Authorized JavaScript origins: `http://localhost:3000` **and** your Vercel URL (e.g. `https://examini.vercel.app`) once deployed.
3. Copy the **Client ID** into both:
   - `backend/.env` → `GOOGLE_CLIENT_ID=...` (and `GOOGLE_CLIENT_SECRET` if shown)
   - `frontend/.env.local` → `NEXT_PUBLIC_GOOGLE_CLIENT_ID=...` (same value in Vercel env vars)

**Behavior reminder:** the backend's Google login is **login-only** — it rejects Google tokens for emails that don't already exist as users. Create the account (via admin panel) first, then Google sign-in works for it. Leaving OAuth unconfigured is also fine; the button simply won't function.

---

## 5. Deployment

### 5.1 Backend → Render (free)

1. Push the repo to GitHub.
2. [render.com](https://render.com) → **New → Web Service** → connect the repo, root directory `backend/`.
3. Build command: `pip install -r requirements.txt`
   Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Environment variables on Render:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | Neon connection string |
   | `JWT_SECRET_KEY` | same strong secret as local (or a new one) |
   | `OPENAI_API_KEY` | Gemini API key |
   | `OPENAI_MODEL` | `gemini-2.5-flash` |
   | `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | from Cloudinary dashboard |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from Google Console (optional) |
   | `CORS_ORIGINS` | `https://<your-app>.vercel.app,http://localhost:3000` |
   | `DEBUG` | `False` |

5. Note the service URL, e.g. `https://examini-api.onrender.com`.

**Free-tier tradeoff:** Render free services **sleep after ~15 min idle**; the first request after that takes ~30–60s to wake. Acceptable for demos/small use.

### 5.2 Frontend → Vercel (free)

1. [vercel.com](https://vercel.com) → **Add New → Project** → import the repo, set **Root Directory = `frontend/`** (framework auto-detects Next.js).
2. Environment variables:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://examini-api.onrender.com` (no trailing slash) |
   | `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Google OAuth Client ID (optional) |

3. Deploy → get `https://<your-app>.vercel.app`.
4. Go back and add this URL to Render's `CORS_ORIGINS` **and** Google OAuth's Authorized JavaScript origins.

---

## 6. Final Checklist

**One-time accounts:** ☐ Neon ☐ Cloudinary ☐ Google AI Studio (Gemini key) ☐ Google Cloud (OAuth) ☐ Render ☐ Vercel ☐ GitHub repo pushed

**Code changes (backend only — frontend needs zero changes):**
- ☐ `config.py`: Supabase settings optional + Cloudinary settings added
- ☐ `pyproject.toml` / `requirements.txt`: remove `supabase`, add `cloudinary`
- ☐ New `services/storage_service.py`
- ☐ `routes/teacher.py`: upload → Cloudinary; download → proxy
- ☐ `routes/student.py`: view + download → proxy
- ☐ `services/openai_service.py`: Gemini `base_url`

**Database:** ☐ Migrations 01–04, 06 (real bcrypt hash), 07 run on Neon — 05 skipped

**Verify locally before deploying:** `/health` OK → admin login → create class/section → register student → upload material (check it appears in the Cloudinary media library) → download/view it → generate exam with AI → publish → take it as the student → see the result.

**Known pre-existing gaps NOT addressed by this migration** (see `report.md` §5): AI reads filenames not file contents; forgot-password sends no email (would need Resend/Brevo free tier); no manual grading UI for text answers; result-visibility settings and teacher-class scoping unenforced; hardcoded UTC−5 Pakistan time offset in backend + frontend.
