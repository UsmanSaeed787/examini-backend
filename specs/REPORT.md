# Examini — Architecture Audit Report

> System of Record (SOR) produced per the brief in `SMR.md`. This report documents **only what exists in the repository** as of 2026-07-25. It contains no redesign proposals and no implementation suggestions. Where something is absent, it is explicitly stated as missing.

---

# 1. Executive Summary

**What this platform is.** Examini is a full-stack exam management system for schools/academies, tailored to Pakistani institutions (CNIC/B-Form identity numbers, provinces/domicile, roll numbers, Pakistan-time handling). It consists of two independent applications: a Python **FastAPI + SQLAlchemy** backend (`backend/`) exposing a JSON API, and a **Next.js 16 App Router** frontend (`frontend/`) consuming it. There is no monorepo tooling; each app is installed and run separately.

**What problem it solves.** It digitizes the exam lifecycle for three roles: an **Admin** manages users, classes, sections, and student registration; **Teachers** upload course materials, create exams manually or generate them with an LLM from uploaded material text, publish exams, and view results; **Students** take timed online exams within a date window and see auto-graded results with grades.

**Current maturity.** Functional prototype / late-MVP. The core happy path (register student → upload material → create/generate exam → publish → student takes exam → auto-graded result) works end-to-end. However: there are **zero automated tests** (backend `tests/` is empty; frontend has no test framework), no CI configuration, no migration runner, substantial dead code on both sides, several half-built features (notifications, audit logs, question bank, exam-section assignment, result-visibility permissions, password-reset email), and multiple known correctness and security gaps documented in §15–§17.

**Overall architecture.** Classic three-tier: a stateless-ish REST API (JWT auth with DB-persisted refresh sessions) over PostgreSQL, with files in Cloudinary and LLM calls to OpenAI or Google's OpenAI-compatible Gemini endpoint. The frontend is an almost entirely client-rendered SPA built on the App Router (61 of 63 components are `'use client'`; there is no `middleware.ts`, no server-side data fetching, and no Next.js API routes).

**Major strengths.**
- Clean, consistent backend layering (routes → services → models/schemas) with a role-based dependency system.
- A single, well-behaved frontend API client with transparent token refresh.
- A thorough relational schema (20 tables, 48 indexes, UUID PKs, junction tables, CHECK constraints) that anticipates features beyond what the app currently uses.
- Uniform custom-exception error envelope on the backend (where used).
- ORM-only data access — no raw SQL in application code, so no SQL-injection surface in `app/`.

**Major weaknesses.**
- **No tests of any kind**, no CI, no migration tracking.
- **Authorization is coarse**: teacher↔class assignments exist in the schema but are enforced nowhere; teachers can manage every student and class in the system.
- **Exam integrity is client-trusted**: duration and end-date are not enforced server-side at submit time; the timer is client-clock based; there are no anti-cheat measures.
- **Grading logic exists in three places plus a DB trigger**, with divergent semantics.
- Security hygiene gaps: tokens in localStorage, plaintext refresh/reset tokens in DB, no rate limiting, `debug=True`, secrets present in `.env`/`.env.bak` (the latter not gitignored), verbose error/PII logging.
- Hardcoded `-5h` "Pakistan offset" duplicated across backend and four frontend locations.

---

# 2. Technology Stack

**Backend**
- Python ≥ 3.10, FastAPI (pyproject: `>=0.109.0`; installed venv: 0.120.4), Uvicorn (standard extras).
- SQLAlchemy 2.x ORM (sync engine, `psycopg2-binary` driver), no Alembic.
- Pydantic v2 + `pydantic-settings` for config (`.env`).

**Frontend**
- Next.js **16.0.1** (App Router), React **19.2.0**, TypeScript 5 (`strict: true`), Tailwind CSS **4** (config-less, tokens in `globals.css`).
- Axios 1.13, Zustand 5 (with `persist`), react-hook-form 7 + zod 4 (`@hookform/resolvers`), react-hot-toast 2, `@react-oauth/google`, clsx + tailwind-merge.
- Declared but never imported: `date-fns`, `lucide-react` (unused dependencies).

**Database**
- PostgreSQL. Migrations were authored for **Supabase** (SQL Editor execution, `auth.uid()` in RLS policy); the current stack targets **Neon** per `update.md`. Extensions enabled: `uuid-ossp`, `pg_trgm`, `btree_gin` (all three effectively unused — see §7).

**Authentication**
- Backend-issued JWTs via `python-jose` (HS256): 30-min access token, 7-day refresh token; refresh tokens persisted in a `sessions` table and rotated. `bcrypt` used directly for password hashing (passlib is declared but deliberately bypassed). Google OAuth **login-only** via ID-token verification (`google-auth`).

**Storage**
- **Cloudinary** (`resource_type="raw"`, folder `examini/materials/`) via `services/storage_service.py`. Legacy local-disk fallback paths remain in download routes; three legacy PDFs still sit in `backend/app/uploads/`.

**State management (frontend)**
- One Zustand store (`store/auth-store.ts`) with dual persistence: the zustand `persist` blob (`auth-storage`) **and** three flat localStorage keys (`access_token`, `refresh_token`, `user`). No other stores.

**Validation**
- Backend: Pydantic schemas per domain (with three endpoints accepting raw untyped `dict` bodies — §15). Frontend: zod schemas in 9 files (login form + 8 modals); all page-level forms use manual `useState` + toast validation instead.

**UI**
- Tailwind CSS 4, custom utility/animation classes in `globals.css`, inline SVG icons (lucide-react unused), dark theme (`bg-gray-900`) with teal brand `#2ab6a5`, react-hot-toast for notifications, hand-rolled modals (no shared Modal primitive).

**AI**
- `openai` SDK. Model from `OPENAI_MODEL` (default `gpt-4o-mini`); if the model name starts with `gemini`, `base_url` switches to `https://generativelanguage.googleapis.com/v1beta/openai/` (Google's OpenAI-compatible endpoint). The deployment's `.env` sets `OPENAI_MODEL=gemini-3.6-flash`, so **Gemini is what actually runs**. Text extraction for prompts via `pypdf` and `python-docx` (`services/parser_service.py`).

**Deployment**
- No Dockerfiles, no CI/CD config, no process manager config in the repo. `update.md` documents the intended targets (backend on Render, frontend on Vercel, DB on Neon) but no deployment artifacts exist in the codebase. `next.config.ts` is an empty object.

**Testing**
- **Missing entirely.** `backend/tests/` is an empty directory; no pytest config; frontend has no test framework or test script.

**Package managers / build tools**
- Backend: `uv` (`uv.lock`, 359 KB, is the real source of truth) with hatchling; a parallel `requirements.txt` exists and is **out of sync** (missing `bcrypt`, `google-auth`, `requests` — a pip install from it cannot start the app). Frontend: npm (`package-lock.json`), Next build pipeline, ESLint 9 with `eslint-config-next` core-web-vitals + typescript presets only.

---

# 3. Repository Structure

```
examini/
├── CLAUDE.md, SMR.md, REPORT.md, spec.md, update.md   # docs (spec.md: material-text-extraction spec; update.md: stack migration plan)
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app: CORS, error handlers, router mounting, /health
│   │   ├── config.py             # pydantic-settings; reads backend/.env
│   │   ├── database.py           # sync SQLAlchemy engine/session (pool_size=10, max_overflow=20, pre_ping)
│   │   ├── api/
│   │   │   ├── deps.py           # HTTPBearer + get_current_user + role guards
│   │   │   └── routes/           # auth.py, admin.py, teacher.py, student.py, exams.py*, materials.py*  (*stubs)
│   │   ├── services/             # auth, user, class, exam, material, student, teacher, result*, openai, parser, storage  (*dead)
│   │   ├── models/               # SQLAlchemy models (20 tables)
│   │   ├── schemas/              # Pydantic request/response schemas per domain
│   │   ├── middleware/error_handler.py  # custom exceptions + 7 global handlers
│   │   ├── utils/                # security.py (JWT/bcrypt), constants.py (enums), helpers.py (grading, pagination)
│   │   └── uploads/              # 3 legacy PDFs (pre-Cloudinary)
│   ├── migrations/               # 01–07 plain SQL, run manually; README documents 01–06 only
│   ├── tests/                    # EMPTY
│   ├── pyproject.toml / uv.lock / requirements.txt   # three-way version drift (§14)
│   └── fix_database_url.py       # helper script; currently does not compile (SyntaxError)
└── frontend/
    ├── app/                      # everything lives here; @/* alias → app/*
    │   ├── layout.tsx            # the ONLY layout (root); fonts, GoogleOAuthProvider, Toaster
    │   ├── page.tsx              # redirect: /dashboard if authed else /login
    │   ├── (auth)/               # /login, /forgot-password, /reset-password
    │   ├── (admin)/              # /users, /classes, /sections  (group strips prefix — admin pages at bare URLs)
    │   ├── dashboard/            # role-switching dashboard page
    │   ├── teacher/…  student/…  # role route trees
    │   ├── components/           # ui/, layouts/, providers/, dashboards/, exams/, forms/, users/, user/*, students/, classes/, sections/, materials/   (*mostly dead duplicate of users/)
    │   ├── lib/                  # api.ts (509-line axios client), constants.ts, utils.ts
    │   ├── store/auth-store.ts   # the only Zustand store
    │   ├── hooks/                # EMPTY directory
    │   └── types/                # user.ts, exam.ts, student.ts, common.ts
    └── next.config.ts            # empty config
```

**Architectural boundaries.**
- Backend: routes are thin and delegate to `services/`; models and schemas are kept separate; auth crosses layers only through `api/deps.py`. The boundary is mostly respected, with one major violation: the live grading engine (`calculate_and_save_result`, ~150 lines) lives at module level **inside** `api/routes/student.py`, not in a service.
- Frontend: the only enforced boundary is the API client (`lib/api.ts`) — all HTTP goes through it. There is no server/client boundary in practice (everything is client-rendered), no shared hook layer (`hooks/` is empty), and no shared modal primitive; each page re-implements auth-guard, fetching, and modal shells.
- Cross-app contract: hand-maintained. TypeScript interfaces in `types/` mirror Pydantic schemas by convention only; most mutating API-client methods are typed `any`, so the contract is not enforced.

---

# 4. Current Product Features

### Module: Authentication
| Feature | Purpose / description | Status | Dependencies |
|---|---|---|---|
| Email/password login | bcrypt verify → access+refresh JWT + `sessions` row | Working | users, sessions |
| Google login | Verifies Google ID token; **existing users only** (no signup); backfills `google_id`/avatar | Working (login-only) | google-auth, `GOOGLE_CLIENT_ID` |
| Token refresh + rotation | `/auth/refresh` rotates both tokens in the same session row | Working | sessions |
| Logout | Deletes matching session (or all for user) | Working | sessions |
| Forgot/reset password | Creates 1-hour single-use token; reset endpoint validates and sets new hash | **Incomplete** — no email is ever sent; token is generated then discarded by the route; endpoint always replies "Password reset email sent" | password_resets |
| Own profile view/update/delete | GET/PUT/DELETE `/auth/profile` (+ `/profile/student`), soft delete | Working | users, student_profiles |

### Module: Admin
| Feature | Purpose / description | Status | Dependencies |
|---|---|---|---|
| User CRUD + bulk create | Paginated list (admins hidden), create any role, update/soft-delete (admins refused) | Working; quirk: an admin can create another admin who is then invisible/unmanageable via the API | users |
| Dashboard stats | Counts of users/teachers/students/classes | Working, except `total_exams` hardcoded `0` (TODO in code) | users, classes |
| Classes & sections CRUD | Sections unique per class; hard deletes cascade | Working; class/section lists unpaginated | classes, sections |
| Teacher↔class assignment | Junction rows in `teacher_classes` | Rows are written but **enforced nowhere** (§6, §15) | teacher_classes |
| Student registration | Creates user + Pakistani-KYC profile + enrollment + auto roll number (`class-section-NN`) + generated password, one transaction | Working; roll-number generation has a read-then-write race | users, student_profiles, student_classes |
| Student management | Paginated list w/ class/section/search filters, detail, profile update | Working | as above |
| Student password change | `PUT /admin/students/{id}/password` **requires the student's current password** — unusable as an admin reset | Broken by design | users |

### Module: Teacher
| Feature | Purpose / description | Status | Dependencies |
|---|---|---|---|
| Dashboard | Global class/student counts + own exam/material counts + 5 recent exams | Working | — |
| Materials CRUD | Multipart upload → Cloudinary; extension whitelist (`pdf,doc,docx,txt,png,jpg,jpeg`), 50 MB cap; edit title/description; soft delete; authenticated proxy download | Working; Cloudinary object never deleted on material delete | Cloudinary creds |
| Manual exam creation | Exam + ordered questions (mcq/true_false/short_answer/long_answer; easy/medium/hard; per-question points) + options in one transaction; default `exam_permissions` row created | Working | exams, questions, question_options |
| AI exam generation | Select materials + question config → parser extracts text (pdf/docx/txt, 60k-char cap each) → LLM returns JSON questions → exam created unpublished | Working; no output-count verification, no token cap, blocks the event loop (§12) | OpenAI/Gemini key, parser, storage |
| Publish/unpublish | `POST /exams/{id}/publish` (multipart form field, not JSON) | Working | exams |
| Results view | Paginated results for own exams (score/percentage/grade) | Working (N+1-heavy) | exam_results |
| Student management | Same powers as admin: create/edit/soft-delete **any** student; list **all** students and classes | Working but unscoped (§15/§16) | — |

### Module: Student
| Feature | Purpose / description | Status | Dependencies |
|---|---|---|---|
| Dashboard | Available/completed counts, up to 5 upcoming exams with countdowns | Working | — |
| Exam list & detail | Exams in enrolled classes, status-filtered; detail serves questions **without** `is_correct` | Working | student_classes |
| Take exam | Start/resume attempt (max_attempts/allow_retake enforced at start), auto-save answers, timed client countdown, auto-submit at zero, manual submit → grading | Working with integrity gaps: duration/end-date not enforced at submit; auto-save payload malformed (§15); `allow_retake=True` disables the attempt cap | exam_attempts, exam_responses |
| Auto-grading | MCQ/true_false graded by exact set-equality of selected vs correct option IDs; text answers `is_correct=NULL`, 0 points; grade ladder A+…F, pass ≥ 50% | Working for objective questions; **no manual grading exists** so text answers are permanently 0 | exam_results |
| Results | List + detail with full answer key post-submission; student-triggered `recalculate` endpoint; debug `responses` endpoint | Working; visibility permissions ignored; answer key + retake combination leaks answers (§16) | exam_results |
| Materials | List/detail/inline-view/download from enrolled classes, proxied through the API | Working | materials |

### Schema-only features (no application code)
Question bank (`question_bank` table + model), notifications (`notifications`), audit logging (`audit_logs`), exam-to-section assignment (`exam_sections` — never written), result-visibility permissions (`exam_permissions` — written with defaults, never read).

---

# 5. User Roles

Roles are the `UserRole` enum (`admin`, `teacher`, `student`) in `backend/app/utils/constants.py`, stored as a plain `VARCHAR(20)` with a CHECK constraint. Frontend mirrors this in `types/user.ts`, though most frontend role checks compare raw string literals.

### Admin
- **Permissions:** everything under `/api/admin/*` (25 endpoints), via `get_admin_user`.
- **Pages:** `/dashboard` (admin variant), `/users`, `/classes`, `/sections` (the `(admin)` route group strips its prefix, so these are bare URLs).
- **Capabilities:** user CRUD + bulk create; class/section CRUD; teacher↔class assignment; full student registration/management.
- **Restrictions:** cannot edit/delete admin accounts via API (`UserService` refuses); admin rows are hidden from the user list; the student-password endpoint demands the student's current password, making admin resets impossible.
- **Workflow:** log in → dashboard → manage users/classes/sections → register students into class+section (roll number and password auto-generated) → assign teachers to classes (no downstream effect).

### Teacher
- **Permissions:** everything under `/api/teachers/*` (21 endpoints), via `get_teacher_user`.
- **Pages:** `/dashboard` (teacher variant), `/teacher/exams` (+`/create`, `/generate`, `/[id]`, `/[id]/edit`), `/teacher/materials`, `/teacher/results`, `/teacher/students`.
- **Capabilities:** materials CRUD, exam creation (manual and AI), publish/unpublish, results viewing, and full student management (register/edit/soft-delete any student).
- **Restrictions:** only their **own** materials and exams are readable/editable (ownership checked). But class scoping is absent — teachers see **all** classes and **all** students regardless of `teacher_classes` assignments; both `verify_teacher_class_access` implementations exist and are never called.
- **Workflow:** log in → dashboard → upload material to any class → create exam manually or via AI from materials → publish with date window → view results as students submit.

### Student
- **Permissions:** everything under `/api/students/*` (15 endpoints), via `get_student_user`. Data is scoped to enrolled classes via `student_classes`.
- **Pages:** `/dashboard` (student variant), `/student/exams` (+`/[id]` taking, `/[id]/result`), `/student/materials` (+`/[id]` viewer), `/student/results`.
- **Capabilities:** browse/view/download materials; take published exams in-window; view results with correct answers; trigger result recalculation on own attempts.
- **Restrictions:** enrollment-checked on exams and materials; cannot see `is_correct` while taking an exam.
- **Workflow:** log in → dashboard shows upcoming exams with countdowns → start exam when window opens → answer with auto-save under a countdown → submit (or auto-submit at zero) → view graded result.

---

# 6. Authentication & Authorization

**JWT.** `utils/security.py` issues HS256 tokens signed with `JWT_SECRET_KEY`. Access token: `{sub: user_id, role, exp, type:"access"}`, 30 minutes. Refresh token: `{sub, exp, type:"refresh"}`, 7 days. No issuer/audience claims, no JTI, no revocation list. `datetime.utcnow()` (naive, deprecated) is used here, while other modules use aware UTC — mixed datetime disciplines. Passwords hashed with **bcrypt directly** (passlib deliberately bypassed); inputs silently truncated to 72 bytes; policy: ≥8 chars, upper+lower+digit.

**Refresh tokens.** Persisted **in plaintext** in `sessions.refresh_token` (unique). Refresh flow: verify JWT type → exact-string session lookup with `expires_at > now` → user must match and be active → mint a new pair and overwrite the same session row (rotation without reuse detection). Session expiry is hardcoded `timedelta(days=7)` in three places in `auth_service.py`, ignoring the `refresh_token_expire_days` setting — changing the setting desyncs JWT expiry from DB session expiry.

**Google OAuth.** Single endpoint `POST /api/auth/google`: frontend obtains a Google **ID token** via `@react-oauth/google`; backend verifies it with `google.oauth2.id_token.verify_oauth2_token` (60 s clock skew). Unknown emails are rejected ("contact administrator") — login only, no signup. `google_client_secret` and `google_redirect_uri` are configured but **never used**; no server-side authorization-code callback route exists despite the configured `/api/auth/google/callback` URI.

**RBAC.** `api/deps.py`: `HTTPBearer()` → `get_current_user` verifies the access JWT and loads the active user from the DB (the token's `role` claim is *not* trusted; role is re-read from the row). Role guards `get_admin_user` / `get_teacher_user` / `get_student_user` do strict single-role equality and raise `AuthorizationError` (403). A `require_role(*roles)` factory exists but is **never used** (imported once, unused). Note: `HTTPBearer`'s default `auto_error=True` returns **403** (not 401) for a missing Authorization header.

**Permission flow.** Request → Bearer token → `get_current_user` (401 on bad/expired token or inactive user) → role guard (403 on role mismatch) → route-level ownership/enrollment checks in services (e.g., material owner, exam owner, student enrollment). There is **no** row-level scoping between teachers and classes (assignments unenforced), and the DB provides no defense-in-depth (RLS effectively unused — §7).

**Middleware.** No auth middleware; auth is entirely dependency-injection based. The only middleware is CORS (origins from env, currently two localhost origins; credentials allowed; all methods/headers). No TrustedHost, no security headers, no rate limiting, no request logging.

**Frontend auth flow.** Login stores tokens + user in localStorage (twice — zustand `persist` blob and flat keys). Axios request interceptor attaches the Bearer token; response interceptor transparently refreshes on 401 (excluding auth endpoints and 404s), replays the original request, and hard-redirects to `/login` on refresh failure. There is **no refresh de-duplication** — N concurrent 401s trigger N parallel refresh calls, which combined with server-side rotation can invalidate each other. Route protection is 100% client-side (no `middleware.ts`): an inline guard block copy-pasted into 18 of 22 pages checks `isAuthenticated` and `user.role` from localStorage. Server-side authorization on the API is the only real barrier.

**Security architecture summary.** Single trust boundary at the API; JWT bearer over CORS-restricted HTTP; DB accessed with one privileged connection string; secrets in `.env` (see §16 for exposure issues).

---

# 7. Database Analysis

**20 tables** (19 in migration 02, `student_profiles` in 07). All PKs are `UUID DEFAULT gen_random_uuid()`; all timestamps `TIMESTAMPTZ`. There are **no Postgres ENUM types** — every enum-ish column is `VARCHAR` + CHECK. **48 indexes** total (43 in migration 03, 5 in 07).

### Primary entities and ownership

| Table | Business owner | Purpose |
|---|---|---|
| `users` | Admin | All accounts; `role` CHECK (admin/teacher/student); `is_active` soft delete; nullable `password_hash` (OAuth); unique `email`, `google_id` |
| `sessions` | System | Persisted refresh tokens (plaintext, unique), expiry, device/ip columns (ip never populated) |
| `password_resets` | System | Single-use reset tokens (plaintext), 1-hour expiry, `used_at` |
| `classes` / `sections` | Admin | Sections unique per class (`UNIQUE(class_id, name)`); `classes.created_by → users` (NO ACTION — user deletion fails if they created a class) |
| `teacher_classes` | Admin | Teacher↔class junction, `UNIQUE(teacher_id, class_id)`; **written but never enforced** |
| `student_classes` | Admin | Enrollment junction `UNIQUE(student_id, class_id, section_id)`; carries `roll_number` (nullable; unique per class+section via partial index — not globally unique) |
| `student_profiles` | Admin | 1:1 with users; Pakistani KYC (unique CNIC/B-Form, father name, DOB with two `CURRENT_DATE` CHECKs, gender/nationality/domicile/marital CHECKs). No `role='student'` enforcement — any user row can own one. RLS never enabled on it |
| `materials` | Teacher | File metadata; `file_url` (Cloudinary URL or legacy path), soft delete; uses `uploaded_at` instead of `created_at` |
| `exams` | Teacher | duration, start/end window, `is_published`, `allow_retake`, `max_attempts` (no CHECKs on duration > 0, end > start, or max_attempts ≥ 1) |
| `exam_sections` | Teacher | Exam↔section junction — **never written by any code** |
| `questions` / `question_options` | Teacher | Ordered questions (`UNIQUE(exam_id, order_number)`), type/difficulty CHECKs, `points DECIMAL(5,2)`; options ordered and flagged `is_correct` |
| `question_bank` | Teacher | Island table (teacher_id + text/type/difficulty/tags TEXT[] + GIN index) — no FK linkage to questions/exams, no options, no points; **completely unused** |
| `exam_attempts` | Student | `UNIQUE(exam_id, student_id, attempt_number)`; status CHECK (`in_progress/submitted/timeout/abandoned` — the last two never set by code) |
| `exam_responses` | Student | One per attempt+question (`UNIQUE(attempt_id, question_id)`); `answer_text` or `selected_options UUID[]` (**no FK from array elements to question_options** — dangling IDs possible); tri-state `is_correct` |
| `exam_results` | System | 1:1 with attempt (`attempt_id` UNIQUE); score/max/percentage/grade/passed; `reviewed_at/reviewed_by/feedback` **never written** (no manual review exists) |
| `exam_permissions` | Teacher | 1:1 with exam; visibility settings — **written with defaults on exam creation, never read** |
| `notifications` | System | Polymorphic (`related_entity_type/id`, no FK) — **unused** |
| `audit_logs` | System | Polymorphic, JSONB details, `user_id` SET NULL — **unused; no audit logging exists** |

### ER summary (text)

```
users 1──N sessions, password_resets, notifications, materials(teacher), exams(teacher),
          question_bank(teacher), exam_attempts(student), classes(created_by), audit_logs(SET NULL)
users 1──1 student_profiles (user_id UNIQUE, CASCADE)
users M──N classes   via teacher_classes  (UNIQUE pair)
users M──N classes   via student_classes  (UNIQUE triple; +roll_number; section_id NOT NULL)
classes 1──N sections (UNIQUE(class_id,name)), materials, exams, both junctions
sections M──N exams  via exam_sections    (never populated)
exams 1──N questions (UNIQUE order), 1──N exam_attempts, 1──1 exam_permissions
questions 1──N question_options (UNIQUE order), 1──N exam_responses
exam_attempts 1──N exam_responses (UNIQUE attempt+question), 1──1 exam_results
exam_responses.selected_options UUID[] ──> question_options.id   (soft reference, no FK, no index)
question_bank = island (only linked to users)
```

26 FK edges: 24 CASCADE, 1 SET NULL (`audit_logs.user_id`), 2 default NO ACTION (`classes.created_by`, `exam_results.reviewed_by` — both also lack supporting indexes).

### Functions, triggers, RLS
- `update_updated_at_column()` + BEFORE UPDATE triggers on users/classes/sections/materials/exams/question_bank; migration 07 adds a **byte-identical duplicate function** for `student_profiles`.
- `calculate_exam_result()` — an AFTER UPDATE trigger on `exam_attempts` (status → 'submitted') that inserts/upserts `exam_results` **in SQL**, duplicating the Python grading. Critically, its `max_score` sums points only over **answered** questions (answer 1 of 20 correctly → 100%), diverging from the Python engine which sums all questions. The Python write happens after and wins in practice, but two grading authorities exist.
- `generate_roll_number(class,section)` — defined in SQL but never wired to a trigger/default; the backend implements its own Python version instead. The SQL version breaks on class names containing `-` (integer cast of `SPLIT_PART`).
- `cleanup_expired_sessions()` — defined, never scheduled; expired sessions accumulate.
- **RLS**: enabled on all 19 original tables but **exactly one policy exists** (users self-select via Supabase's `auth.uid()` — non-portable off Supabase; migration 05 fails on vanilla Postgres/Neon). Comments in the file state access control is intentionally delegated to FastAPI. Net: RLS provides zero effective protection; the app connects with a privileged role.

### Notable schema observations (from the SQL alone)
- All three extensions are unused by any index/default actually defined (`gen_random_uuid()` is the PG13+ builtin, no trigram or btree_gin usage).
- ~8 redundant duplicate indexes shadowing UNIQUE constraints (email, refresh_token, reset token, attempt_id, exam_id, user_id ×3 on student_profiles, cnic).
- Index naming bug: `idx_student_profiles_class_section` is actually on `(user_id)`.
- No migration tracking table, no transaction wrappers; files 02–05 are not re-runnable.
- README documents migrations 01–06 only; 07 is undocumented; README still calls the seeded admin hash a placeholder while 06 now contains a real bcrypt hash for `Admin@123` (plaintext password committed in comments).

---

# 8. Backend Architecture

**FastAPI app** (`app/main.py`): CORS middleware → `setup_error_handlers(app)` → six routers mounted under `/api/*` → `/` and `/health` (no DB check). `debug=settings.debug` (default **True**); `/docs` and `/openapi.json` always exposed.

**Routers** (`api/routes/`): `auth` (10 endpoints), `admin` (25), `teacher` (21), `student` (15), plus `exams` and `materials` — **both single-endpoint "Not implemented yet" stubs that are nonetheless mounted and appear in OpenAPI**. Routes are mostly thin, with exceptions: the grading engine and a Pakistan-offset date check live inside `student.py`; a section-detail query and teacher-unassign are inlined in `admin.py`.

**Services** (`services/`): one per domain, all-static-method classes. `AuthService`, `UserService`, `ClassService`, `StudentService` (incl. password/roll-number generators), `TeacherService`, `MaterialService`, `ExamService`, `OpenAIService`, `ParserService`, `StorageService` — and `ResultService`, which is **entirely dead** (never imported; grading is inlined in `routes/student.py`). Both `verify_teacher_class_access` helpers (in `TeacherService` and `MaterialService`) exist and are never called.

**Models** (`models/`): 20 SQLAlchemy models mirroring §7; UUID PKs, timezone-aware timestamps, relationship graphs with cascade delete-orphan from `User`. No SQLAlchemy Enum columns — enum values compared as strings against `utils/constants.py` enums.

**Schemas** (`schemas/`): Pydantic v2 request/response models per domain (`auth`, `user`, `class_schema`, `student`, `material`, `exam`, `result`, `common` with `PaginatedResponse`/`MessageResponse`). Gaps: `PaginatedResponse` used unparameterized on three endpoints (untyped `items`); several schemas are dead (`ExamPublish`, `ExamSectionAssign`, `ExamPermissionUpdate`, `ResultDetailResponse`, `StudentCreate`, `UserDetail`); three endpoints take raw `dict` bodies; `ExamCreate` lacks bounds (duration may be ≤ 0, questions may be empty, end before start).

**Dependencies** (`api/deps.py`): see §6.

**Utilities** (`utils/`): `security.py` (JWT + bcrypt + password policy), `constants.py` (5 enums; `ResultsVisibleTo` unused; `TIMEOUT/ABANDONED` statuses never set), `helpers.py` (grading ladder `calculate_grade` — the single grading scale, pass hardcoded at 50% — plus `paginate_response`; `validate_email`, `parse_file_size`, `sanitize_filename` are unused).

**Middleware / error handling** (`middleware/error_handler.py`): custom exceptions (`AuthenticationError` 401, `AuthorizationError` 403, `NotFoundError` 404, `ValidationError` 422, `DatabaseError` — declared, no handler, never raised) plus handlers for `RequestValidationError`, `SQLAlchemyError`, and a catch-all, all returning `{"error": {code, message, details}}`. **No `HTTPException` handler**, and ~40 routes still raise bare `HTTPException` — so the API emits **two incompatible error envelopes**. No logging in any handler; unexpected exceptions are swallowed without server-side traceback records.

**Configuration** (`config.py`): see §13.

**Business layer**: transactional writes per service call (e.g., exam + questions + options + permission in one commit; student user + profile + enrollment in one commit). Grading: MCQ/true_false set-equality; `short_answer`/`long_answer` → `is_correct=None`, 0 points, no review path.

**File uploads**: multipart → extension whitelist → **whole file read into memory before the size check** → inline filename sanitation (ignoring the `sanitize_filename` helper) → Cloudinary `raw` upload under `examini/materials/{uuid}_{name}` → DB row. Downloads/views proxy bytes through the API (auth preserved); legacy local-disk fallback paths compute **different base directories** in teacher vs student routes; `Content-Disposition` built by unescaped f-string interpolation of the stored filename.

**Background tasks**: **none.** No `BackgroundTasks`, no queue/worker. AI generation, Cloudinary I/O, PDF/DOCX parsing, and all DB access run synchronously inside `async def` handlers — the LLM call blocks the entire event loop for its duration.

---

# 9. Frontend Architecture

**Next.js routing.** 22 routes (see map in §3/§10-consumers). One root `layout.tsx` only — no nested layouts, no `loading.tsx`/`error.tsx`/`not-found.tsx`, **no `middleware.ts`**, no `route.ts` API routes. The `(admin)` route group strips its prefix, so admin pages occupy bare top-level URLs (`/users`, `/classes`, `/sections`) alongside namespaced `/teacher/*` and `/student/*` trees.

**Layouts.** `app/layout.tsx` (server component) sets the Inter font (all 9 weights + italic), metadata, `GoogleOAuthProviderWrapper`, and the toast `<Toaster>`. `DashboardLayout` (446 lines) is **not** a Next layout — it's a plain client component imported by 20 pages: role-driven collapsible sidebar (nav arrays hardcoded per role; the `role` prop is chosen by the page author, not derived from the user), inline SVG icons, hand-computed dropdown positioning, and the logout modal pair.

**Pages.** Every page is `'use client'` (61 of 63 files; only the root layout and `ui/button.tsx` are server components). All three dashboards are `next/dynamic` with `ssr: false`. Net effect: no SSR of meaningful content, a spinner/skeleton flash on every navigation, and no server-side data fetching anywhere.

**Components.** `ui/` primitives: `Button` (5 variants), `Input` (no `forwardRef` — react-hook-form `register` refs are silently dropped), `Skeleton` family. **No Modal primitive** — 13 modals hand-roll their own shells. Feature folders: `dashboards/` (3, one per role), `exams/` (countdown, simulated generation stepper, deleting modal), `forms/` (login form — the only RHF+zod form outside modals), `students/`, `classes/`, `sections/`, `materials/`, `users/` (live: table, create/edit modal, 1130-line profile modal, dropdown, logout modals, delete-confirm) and `user/` — a near-duplicate sibling folder where 3 of 4 files are dead divergent copies (different prop contracts and opposite color themes) and one (`logging-out-modal`) is live. `dashboard-layout.tsx` imports from **both** folders on adjacent lines.

**State management.** One Zustand store (`auth-store.ts`) with dual persistence (zustand `persist` blob + three flat localStorage keys; `initialize()` reads only the flat keys). No server-state library (no React Query/SWR) — every page fetches imperatively in `useEffect` with local `useState`.

**API layer.** `lib/api.ts` (509 lines): one axios instance; request interceptor attaches the Bearer token and fixes FormData Content-Type; response interceptor performs the 401 refresh-and-replay flow (§6). Exposes `authApi` (11 methods), `adminApi` (23), `teacherApi` (21), `studentApi` (14) — thin wrappers returning `response.data`, with **hardcoded path strings** (the `API_ENDPOINTS` catalog in `constants.ts` is dead code, 0 references). Most mutating methods are typed `any`.

**Forms & validation.** Two coexisting paradigms split along the modal/page boundary: react-hook-form + zod in the login form and 8 modals; raw `useState` objects with manual `if (!x) toast.error(...)` validation in every page-level form (exam create/edit/generate, exam taking). Toasts via react-hot-toast in 28 files with ad-hoc 2–4-level optional-chain error extraction repeated everywhere.

**Authentication flow (client).** Root `/` redirects by auth state. `/login` renders the RHF form + optional GoogleLogin button; on success it re-reads the `user` JSON from localStorage and branches on role — where **all three branches push the identical `/dashboard`** (block duplicated twice in the file). Protected pages run the copy-pasted `initialize()`/guard/spinner block (18 of 22 pages). Guard gaps: `/dashboard` checks auth but not role; `/forgot-password` and `/reset-password` have no guard at all.

**Exam-taking UI** (`student/exams/[id]/page.tsx`, 523 lines, everything inlined — no Timer or question-form components): loads exam → client-side window check using a hardcoded −5h offset → resumes or starts an attempt → 1 s `setInterval` timer computed from `attempt.started_at` + duration (without the −5h treatment applied to the window check — two timezone models in one file) → radio/textarea inputs per question type with per-keystroke auto-save whose payload is malformed and whose errors are swallowed (`.catch(() => {})`) → navigator grid → `window.confirm` submit or auto-submit at zero → result page. Local interfaces are redeclared instead of importing `types/exam.ts`, and the local `QuestionOption` includes `is_correct`. **No anti-cheat measures of any kind** (no visibility/blur detection, no beforeunload warning, no navigation blocking).

**Reusable-code posture.** `hooks/` is an **empty directory** — zero custom hooks; auth-guard, fetch, and error-extraction logic are duplicated across pages. Duplicated functions: `formatTime` (utils + exam page), `formatExamDateTime` (two files), the guard block (18 pages), the login role-branch (twice in one file).

---

# 10. API Analysis

75 endpoints total (2 app-level, 73 across six routers). All routes below require the listed role dependency unless marked public. Consumers are the corresponding frontend API-client groups (`authApi`, `adminApi`, `teacherApi`, `studentApi`); the two stub routers have no consumers.

### App-level (public)
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Name/version banner |
| GET | `/health` | Liveness (no DB check) |

### `/api/auth` (10) — consumer: `authApi`
| Method | Path | Auth | Purpose | In → Out |
|---|---|---|---|---|
| POST | `/login` | public | Email/password login | `LoginSchema` → tokens + user |
| POST | `/google` | public | Google ID-token login (existing users only) | `GoogleAuthSchema` → tokens + user |
| POST | `/refresh` | public | Rotate token pair | `RefreshTokenSchema` → `TokenResponse` |
| POST | `/logout` | user | Delete session | `RefreshTokenSchema` → message |
| POST | `/forgot-password` | public | Create reset token (no email sent) | email → always-success message |
| POST | `/reset-password` | public | Reset by token | token+password → message |
| GET/PUT/DELETE | `/profile` | user | Own profile read/update/soft-delete | `UserUpdate` → dict |
| PUT | `/profile/student` | user (student-only inline check) | Own student profile | **raw dict** → dict |

### `/api/admin` (25) — all `get_admin_user`; consumer: `adminApi`
Users: list (paginated, admins hidden) / get / create (any role) / update / soft-delete / bulk-create. Dashboard stats (`total_exams` hardcoded 0). Classes: list (unpaginated) / get / create / update / hard-delete. Sections: list / get / create-under-class / update / hard-delete. Teacher assignment: assign / unassign. Students: register (user+profile+enrollment+roll no.) / list (filters) / detail / profile-update / password-change (**raw dict**, requires current password) / list-by-class-section (unpaginated).

### `/api/teachers` (21) — all `get_teacher_user`; consumer: `teacherApi`
Dashboard; results list (paginated, hand-built dicts); students list/register/detail/profile-update/soft-delete (**globally scoped — all students**); classes list (**all classes**); materials list/upload/detail/download-proxy/update/soft-delete; exams list (in-memory pagination)/detail (includes `is_correct`)/create/AI-generate/update/publish (multipart form bool)/hard-delete.

### `/api/students` (15) — all `get_student_user`; consumer: `studentApi`
Dashboard; exams list (status filter)/detail (no `is_correct`, includes current attempt); attempt start/get/auto-save (**raw dict**)/submit/recalculate/debug-responses; materials list/detail/view-inline/download; results list/detail (full answer key).

### `/api/exams`, `/api/materials` (1 each) — stubs
`GET /{id}` under `get_current_active_user` returning `{"message": "Not implemented yet"}`. Mounted and visible in OpenAPI; no consumers.

**Cross-cutting API observations.** Mixed error envelopes (custom `{"error":…}` vs FastAPI `{"detail":…}`); three raw-dict request bodies bypassing validation; three unparameterized `PaginatedResponse` uses; several endpoints return `str(exception)` to clients unconditionally; a debugging endpoint (`GET …/attempts/{id}/responses`) is live in production; publish takes multipart form data while everything else is JSON.

---

# 11. Business Workflows

### 11.1 Authentication (email/password)
```
User → POST /api/auth/login {email, password}
  → AuthService.login: bcrypt verify → is_active check
  → mint access JWT (30 min) + refresh JWT (7 d) → INSERT sessions row
  → response {access_token, refresh_token, user}
Frontend → store tokens+user in localStorage (×2 locations) → redirect /dashboard
Every request → Authorization: Bearer <access>
On 401 → POST /api/auth/refresh → session row rotated in place → replay original request
Logout → POST /api/auth/logout → DELETE session → clear localStorage → /login
```

### 11.2 Google login
```
GoogleLogin button → Google ID token → POST /api/auth/google
  → verify_oauth2_token(client_id, 60s skew)
  → user lookup by email — MUST already exist (else "contact administrator")
  → backfill google_id/avatar, email_verified=True → tokens + session (as 11.1)
```

### 11.3 Password reset (incomplete by design)
```
POST /api/auth/forgot-password {email}
  → if user exists: INSERT password_resets {uuid token, +1h expiry}
  → token is RETURNED BY THE SERVICE AND DISCARDED BY THE ROUTE — no email integration
  → response is always "Password reset email sent"
POST /api/auth/reset-password {token, new_password}   ← unreachable by a real user
  → validate unused+unexpired → validate_password → set hash → mark used_at
```

### 11.4 Student registration (admin or teacher)
```
POST /api/admin/students  (or /api/teachers/students)  {StudentRegistrationCreate}
  → StudentService.create_student_with_profile (single transaction):
      1. uniqueness checks (email, CNIC/B-Form — app-level)
      2. generate_password(12)  (secrets-based, rule-fixed first/last chars)
      3. INSERT users {role: student}
      4. INSERT student_profiles {KYC fields}
      5. generate_roll_number: "{class}-{section}-{NN}"  (Python MAX+1 — read-then-write race)
      6. INSERT student_classes {class, section, roll_number}
  → response includes the generated credentials for the operator to hand over
```

### 11.5 Teacher & class management
```
Admin → POST /api/admin/classes → POST /api/admin/classes/{id}/sections
Admin → POST /api/admin/users {role: teacher}
Admin → POST /api/admin/classes/{cid}/teachers/{tid} → INSERT teacher_classes
  ⚠ downstream: NOTHING reads teacher_classes — teachers operate on all classes/students
```

### 11.6 Material upload & consumption
```
Teacher → multipart POST /api/teachers/materials {file, title, class_id, description}
  → extension whitelist (pdf,doc,docx,txt,png,jpg,jpeg) → read all bytes → ≤50 MB check
  → sanitize filename (inline regex) → Cloudinary upload raw: examini/materials/{uuid}_{name}
  → INSERT materials {file_url=secure_url, file_name, file_type, file_size}
Student → GET /api/students/materials            (enrollment-scoped list)
        → GET /api/students/materials/{id}/view      (inline; MIME by extension)
        → GET /api/students/materials/{id}/download  (attachment)
  → backend proxies bytes from Cloudinary (httpx) so bearer auth is enforced
Teacher delete → is_active=False (Cloudinary object left in place)
```

### 11.7 Manual exam creation
```
Teacher → /teacher/exams/create (raw useState form)
  → POST /api/teachers/exams {ExamCreate: metadata + questions[{text,type,difficulty,points,order,options[]}]}
  → ExamService.create_exam: one transaction → exams + questions + question_options
    + exam_permissions row (defaults; never read afterwards)
  → exam is unpublished until POST /exams/{id}/publish (multipart is_published bool)
```

### 11.8 AI exam generation
```
Teacher → /teacher/exams/generate: pick materials + config {total, easy/medium/hard, mcq/short/long}
  → client validates counts sum; shows SIMULATED 3-step progress stepper (caps at 99%)
  → POST /api/teachers/exams/generate {ExamGenerate}
      → MaterialService.get_materials_by_ids (ownership-checked)
      → ParserService.extract_text per material:
          fetch bytes (Cloudinary/legacy disk) → pypdf | python-docx | txt decode
          → fail if < 50 chars extracted (scanned docs) → truncate at 60,000 chars each
      → OpenAIService.generate_exam_from_materials:
          model = OPENAI_MODEL (deployed: gemini-3.6-flash → Google OpenAI-compat endpoint)
          prompt = system role + "=== Material: {title} ===" texts + requirements + JSON example
          temperature 0.7, response_format json_object; SYNCHRONOUS — blocks event loop
      → parse JSON (list | {questions} | single object), backfill order_number
      → ExamService.create_exam (same one-transaction path as manual)
  ⚠ no verification of returned question count/mix; off-vocabulary type/difficulty → unhandled 500
```

### 11.9 Exam publishing
```
POST /api/teachers/exams/{id}/publish  (ownership-checked)
  → is_published = true|false; visible to students via enrolled-class lists once published
  Section-level targeting (exam_sections) exists in schema only — never assigned.
```

### 11.10 Exam participation
```
Student dashboard/list → countdown (client, hardcoded −5h offset) → open exam page
  → GET /api/students/exams/{id}   (published + enrolled + in-window checks; −5h PAKISTAN_OFFSET server-side)
  → resume attempt if in_progress else POST /exams/{id}/start:
      guards: published, enrolled, window, submitted_count vs max_attempts
      ⚠ allow_retake=True disables the attempt cap entirely
      ⚠ concurrent starts can create duplicate in_progress attempts
  → client timer: started_at + duration_minutes, 1 s interval
  → answers: radio (mcq/true_false) or textarea (short/long)
      each change → PUT …/responses auto-save  ⚠ malformed payload, errors swallowed
  → submit (confirm dialog) or auto-submit at 0 → POST …/submit {ExamSubmit}
      ⚠ duration and end_date NOT re-checked at submit time
```

### 11.11 Grading & results
```
On submit (routes/student.py, inline engine):
  attempt.status = 'submitted', submitted_at, time_spent_minutes
  per response:
    mcq/true_false → set(selected_option_ids) == set(correct_option_ids) → full points | 0
    short/long     → is_correct = NULL, points_earned = 0   (no manual review exists)
  total = Σ points_earned; max = Σ ALL question points; percentage; grade ladder
  (A+ ≥90, A ≥80, B ≥70, C ≥60, D ≥50, else F; pass = ≥50%)
  UPSERT exam_results
  ⚠ DB trigger calculate_exam_result() fires on the same status flip and writes its own
    result with DIFFERENT max_score semantics (answered-only); Python write wins by ordering
Student → GET /api/students/results, /results/{id} (full answer key incl. is_correct)
Student → POST …/recalculate (re-runs grading on own attempt at will)
Teacher → GET /api/teachers/results (own exams; N+1-heavy)
```

### 11.12 Profile management
```
Any user → GET/PUT /api/auth/profile (email/full_name), DELETE (soft)
Student  → PUT /api/auth/profile/student (raw dict → StudentUpdate)
Admin/Teacher → PUT …/students/{id}/profile (KYC edit; full payload incl. CNIC logged at INFO)
```

**Assignments** (homework/coursework): no such feature exists anywhere in the codebase — exams and materials are the only content types.

---

# 12. AI Analysis

**Current implementation.** One service, `app/services/openai_service.py`, with a single production capability: generate an exam's questions from uploaded material text. One consumer: `POST /api/teachers/exams/generate`.

**LLM provider & models.** OpenAI SDK pointed at either OpenAI (default) or Google's OpenAI-compatible Gemini endpoint — selected by a string-prefix check on `OPENAI_MODEL` (`startswith("gemini")` → `https://generativelanguage.googleapis.com/v1beta/openai/`). Config default is `gpt-4o-mini`; the deployed `.env` sets `gemini-3.6-flash`, so Gemini is active. Both providers share the single `OPENAI_API_KEY` env var.

**Prompt flow.**
1. Materials fetched and ownership-checked → `ParserService.extract_text` per material (pdf via pypdf page loop; docx paragraphs + table cells; txt utf-8/latin-1) → minimum 50 chars (rejects scanned docs) → truncated at 60,000 chars each (**no cap on material count**, so N × 60k can go into one prompt).
2. Prompt: fixed system message ("expert exam question generator"), user message = material texts under `=== Material: {title} ===` headers + a requirements block interpolated from the untyped `question_config` dict + an inline JSON example.
3. Call: `chat.completions.create`, `temperature=0.7`, `response_format={"type":"json_object"}`. **No `max_tokens`, no timeout, no retries.** The call is synchronous inside an `async def` — it blocks the entire event loop.
4. Output: expected JSON array of `{question_text, question_type, difficulty_level, points, order_number, options[]}`. Parser tolerates a bare list, `{"questions": [...]}`, or a single object; backfills `order_number`. (The prompt asks for a top-level array while `json_object` mode requires an object — the code compensates.)
5. The route builds `Question`/`QuestionOption` rows directly from the parsed dicts.

**Inputs:** teacher-selected material IDs + `question_config` (untyped dict: total, per-difficulty, per-type counts). **Outputs:** an unpublished exam with generated questions/options.

**Limitations (as implemented).**
- No validation that the model honored the requested counts/mix; no schema validation of the output — a missing key raises `KeyError` → unhandled 500; an off-vocabulary `question_type`/`difficulty_level` raises `ValueError` → 500.
- No check that MCQs have ≥1 correct option (such questions score 0 for everyone; only a console warning).
- Raw document text is concatenated into the prompt with no delimiting/escaping — **prompt injection from uploaded documents is possible**.
- Provider errors are wrapped and **returned verbatim to the client** regardless of debug mode.
- No usage quota/rate limit — any teacher can invoke unlimited generations.
- If `OPENAI_API_KEY` is unset, `self.client=None` and `self.model` is never assigned (guarded at the call site by a ValueError).
- Only `pdf/docx/txt` can feed generation, though `doc/png/jpg/jpeg` are uploadable — those materials silently can't be used.

**Current architecture & responsibilities.** AI is a single stateless service call inside one request/response cycle — no streaming, no background jobs, no caching, no evaluation loop, no logging of prompts/outputs, no cost tracking. The frontend's `GenerationProgressStepper` is purely cosmetic (simulated progress capped at 99% until the response lands). No other AI features exist anywhere (no grading assistance, no chat, no analytics).

---

# 13. Configuration

**Backend** (`backend/.env` via pydantic-settings, `app/config.py`; `case_sensitive=False`):

| Variable | Required | Default | Used for |
|---|---|---|---|
| `DATABASE_URL` | **yes** | — | SQLAlchemy engine (Neon/Supabase Postgres) |
| `JWT_SECRET_KEY` | **yes** | — | HS256 signing (no min-length validation) |
| `JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | no | HS256 / 30 / 7 | token lifetimes (refresh-days partially ignored — §6) |
| `GOOGLE_CLIENT_ID` | no | "" | ID-token verification (`CLIENT_SECRET`/`REDIRECT_URI` configured but never used in code) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | no | "" / `gpt-4o-mini` | exam generation; model prefix selects OpenAI vs Gemini endpoint |
| `CLOUDINARY_CLOUD_NAME` / `API_KEY` / `API_SECRET` | no (uploads fail without) | "" | file storage (lazy config) |
| `SUPABASE_URL` / `KEY` / `SERVICE_ROLE_KEY` | no | "" | **legacy — declared, present in .env, never read by code** |
| `DEBUG` | no | **True** | FastAPI debug + some error-detail gating |
| `CORS_ORIGINS` | no | `http://localhost:3000` | comma-separated origin list |
| `MAX_FILE_SIZE_MB` / `ALLOWED_FILE_TYPES` | no | 50 / `pdf,doc,docx,txt,png,jpg,jpeg` | upload validation |
| `UPLOAD_DIR` | no | `uploads` | **never referenced by any code** |
| `APP_NAME` / `APP_VERSION` | no | — | banner/docs |

**Secrets.** `backend/.env` exists on disk with real values (DB URL, JWT secret, Google client secret, OpenAI/Gemini key, Cloudinary secret, legacy Supabase service-role key). **`backend/.env.bak` also contains secrets and is NOT covered by `.gitignore`** (which lists only `.env` and `.venv`). The seed migration commits the admin password `Admin@123` in plaintext comments alongside its real bcrypt hash.

**Frontend** (`frontend/.env.local`): `NEXT_PUBLIC_API_URL` (fallback `http://localhost:8000` — a missing var in production silently targets localhost), `NEXT_PUBLIC_GOOGLE_CLIENT_ID` (a real client ID is present in the working tree; public by design), `NEXT_PUBLIC_APP_NAME` (unused — layout hardcodes the name).

**Configuration files.** `pyproject.toml` (hatchling, uv), `requirements.txt` (drifted), `uv.lock` (authoritative), `tsconfig.json` (strict, `@/*→app/*`), `next.config.ts` (**empty**), `eslint.config.mjs` (Next presets only), `postcss.config.mjs` (Tailwind 4). No Docker/CI/deploy files.

**Runtime configuration.** None beyond env vars — no feature flags, no per-tenant settings.

**External services.** PostgreSQL (Neon/Supabase), Cloudinary, OpenAI or Google Generative Language API, Google OAuth. `fix_database_url.py` (URL-encoding helper) currently fails to compile (`return` at module scope) — it is standalone and unimported.

---

# 14. Dependencies

### Backend (pyproject.toml — 18 declared)
| Dependency | Why it exists |
|---|---|
| fastapi / uvicorn[standard] | API framework + ASGI server (uvicorn is CLI-only; no `__main__` runner) |
| sqlalchemy / psycopg2-binary | ORM + Postgres driver |
| pydantic[email] / pydantic-settings / python-dotenv | schemas, config, .env loading (dotenv consumed indirectly) |
| python-jose[cryptography] | JWT encode/verify |
| bcrypt | password hashing (used **directly**) |
| **passlib[bcrypt]** | **dead** — declared in both files, never imported; code comments say it was deliberately bypassed |
| python-multipart | FastAPI File/Form parsing |
| openai | LLM client (OpenAI + Gemini-compat) |
| httpx | Cloudinary byte fetch-back |
| cloudinary | file storage SDK |
| pypdf / python-docx | material text extraction |
| google-auth | Google ID-token verification |
| **requests** | never imported directly (only the `google.auth.transport.requests` submodule); redundant explicit pin |

**Drift:** `requirements.txt` is missing `bcrypt`, `google-auth`, and `requests` — a pip-only install cannot start the app (direct `import bcrypt` and `google.oauth2` fail). Installed `.venv` versions are far newer than either pin file (e.g. fastapi 0.120.4, openai 2.6.1); `uv.lock` is the effective source of truth. Three-way inconsistency between pyproject / requirements.txt / lockfile.

### Frontend (package.json)
| Dependency | Why it exists |
|---|---|
| next / react / react-dom | framework |
| axios | HTTP client (`lib/api.ts`) |
| zustand | auth store |
| react-hook-form + @hookform/resolvers + zod | validated forms (login + 8 modals) |
| react-hot-toast | notifications (28 files) |
| @react-oauth/google | Google sign-in button |
| clsx + tailwind-merge | `cn()` class helper |
| **date-fns** | **unused** — zero imports; date math is hand-rolled (incl. the −5h offsets) |
| **lucide-react** | **unused** — zero imports; icons are inline SVGs |
| tailwindcss 4 + @tailwindcss/postcss, eslint 9 + eslint-config-next, typescript 5 | build/lint toolchain |

No test dependencies exist on either side.

---

# 15. Code Quality Assessment

**Architecture.** Backend layering is genuinely good and consistently applied — with the notable violation that the production grading engine lives as a module-level function inside `routes/student.py` while a dead `ResultService` occupies the place it belongs. The frontend has an API-client boundary and little else: no hooks layer (empty directory), no server components in practice, no shared modal, two form paradigms.

**Naming.** Mostly clear and conventional on both sides. Standout issues: `components/user/` vs `components/users/` (one-character sibling folders, three dead divergent duplicates, both imported by the same file); DB index `idx_student_profiles_class_section` actually indexes `user_id`; `materials.uploaded_at` standing in for `created_at`.

**Consistency.** Two error envelopes on the API (custom vs `HTTPException`); JSON everywhere except one multipart publish endpoint; three raw-`dict` request bodies; naive vs aware datetimes mixed; `settings` values sometimes ignored in favor of hardcoded literals (7-day session expiry ×3); light-themed modals inside a dark app; role checks via enum in 5 frontend files and string literals in ~17.

**Modularity / reusability.** Backend services are cohesive per domain. Frontend reuse is poor: the ~20-line auth-guard block is copy-pasted into 18 pages; `formatTime`/`formatExamDateTime` are duplicated; exam-taking timer and question renderers are inlined in one 523-line page; 13 modals each hand-roll their shell; interfaces are redeclared instead of imported.

**Scalability (code-level).** In-memory pagination on three list paths (fetch-all-then-slice); pervasive N+1 query loops (no eager loading anywhere in the codebase); unpaginated class/section/roster endpoints; synchronous blocking I/O (DB, Cloudinary, parsing, LLM) inside async handlers — a single AI generation stalls every other request on the worker.

**Maintainability.** Hurt most by: zero tests; schema managed by hand-run SQL with no tracking table (models and DB can drift silently — no Alembic, no `create_all`); three grading implementations plus a semantically different DB trigger; dependency-file drift; heavy `any` usage on the frontend (97 occurrences under `strict: true`, including every mutating API-client method — the typed interfaces are never enforced at the boundary).

**Technical debt & code smells (inventory).**
- *Backend dead code:* `ResultService`; stub routers `exams.py`/`materials.py` (mounted); models `QuestionBank`, `Notification`, `AuditLog`; never-written `ExamSection`; written-never-read `ExamPermission`; both `verify_teacher_class_access` methods; `require_role`; helpers `validate_email`/`parse_file_size`/`sanitize_filename`; enum `ResultsVisibleTo`; statuses `TIMEOUT`/`ABANDONED`; six unused schemas; assorted unused imports; `fix_database_url.py` (doesn't compile); `UPLOAD_DIR` setting; legacy Supabase settings; 3 legacy PDFs in `app/uploads/`.
- *Frontend dead code:* 3 of 4 files in `components/user/`; `API_ENDPOINTS` (29 lines) and `APP_NAME` in constants; `formatDateTime` in utils; `LogoutIcon`; dead `Suspense` import; unused `useRouter`; `date-fns` and `lucide-react`; empty `hooks/`; Next starter SVGs in `public/`.
- *Debug artifacts:* 6 `console.log`s shipped (including one logging exam answers and one logging profile PII); backend `print()`/`traceback.print_exc()` across the grading path including correct-answer UUIDs; `.DS_Store` files committed in both apps.
- *Magic numbers:* −5h Pakistan offset (backend ×2 sites, frontend ×4), 50% pass mark, 60k char cap, 7-day session literal, grade ladder in two languages plus SQL.

**Coupling & cohesion.** Backend coupling is low (services depend on models/schemas only; no service-to-service tangles beyond Teacher→Student). The DB trigger creates hidden coupling between schema and application grading. Frontend pages are each self-contained but couple directly to localStorage shape, response shapes (`error.response?.data?.detail || …data?.error?.message` chains acknowledge the dual envelope), and duplicated timezone logic.

---

# 16. Security Review

**Authentication.**
- Refresh tokens and password-reset tokens stored **in plaintext** in the DB — read access to `sessions`/`password_resets` equals account takeover.
- Access + refresh tokens (and the role-bearing `user` object) live in **localStorage**, in two locations — fully exposed to any XSS; no httpOnly-cookie option exists.
- JWTs lack issuer/audience/JTI; no revocation for access tokens; missing-header responses are 403 instead of 401.
- Password reset is non-functional (no email), yet the endpoint pair is live; responses don't reveal account existence (good), but the flow gives false success messages.
- Frontend refresh flow has no de-duplication; combined with server-side rotation, concurrent 401s can race.

**Authorization.**
- **Teacher over-privilege is the largest gap:** teachers can list, create, edit, and soft-delete *every student in the system* and operate on *any class*; `teacher_classes` is enforced nowhere.
- Result-visibility permissions (`exam_permissions`) are never checked; students always see full answer keys immediately after submission — with `allow_retake=True`, a student can submit, read the key, and retake.
- Student-triggered `recalculate` endpoint lets students re-run grading on their own attempts; a "debugging" per-response correctness endpoint is live.
- Admin-created admins become invisible/unmanageable via the API (list filters them out; update/delete refuse them).

**Input validation.**
- Three endpoints accept raw untyped `dict` bodies; `question_config` is an unvalidated dict; `ExamCreate` allows zero/negative duration, empty question lists, end-before-start windows, unbounded points.
- The AI route indexes LLM output without schema validation (KeyError/ValueError → 500).

**File uploads.**
- Extension-only validation — no MIME sniffing or magic-byte checks; entire file buffered in memory **before** the size check (a 5 GB body is fully read before rejection).
- `Content-Disposition` headers interpolate stored filenames without quote/CRLF escaping (header-injection/filename-spoofing vector).
- Inline `view` route serves content with extension-mapped MIME types including `text/html` (mitigated only because `.html` isn't uploadable today); files are proxied with auth (good).
- Deleted materials leave their Cloudinary objects live at stable URLs.

**SQL injection.** No raw SQL in application code — all ORM with bound parameters. Low risk.

**XSS.** React's default escaping applies; no `dangerouslySetInnerHTML` was observed. Main exposure is the localStorage token store (impact amplifier, not a vector) and the extension-mapped inline viewer noted above.

**CSRF.** Bearer-token auth (no cookies) makes classic CSRF largely inapplicable. CORS is restricted to configured origins, but `allow_credentials=True` with an env-driven free-form origin list means a misconfigured `CORS_ORIGINS=*` would silently produce the dangerous wildcard+credentials combination.

**Secrets & environment.**
- Real secrets present in `backend/.env` **and `backend/.env.bak`, which is not gitignored**.
- Admin seed password `Admin@123` committed in migration comments with its working hash.
- `DEBUG=True` by default and in the deployed env; `/docs` and `/openapi.json` always public.
- ~10 handlers return `str(exception)` to clients unconditionally (SQL fragments, provider errors, paths); AI errors always pass provider text through.
- Backend logs correct-answer UUIDs and full student PII (CNIC, mobile) at INFO/stdout; frontend `console.log`s exam answers and profile data.

**Rate limiting.** **Entirely absent.** Login, Google login, forgot/reset-password, and the admin password endpoint are unthrottled (credential-stuffing/brute-force exposure); AI generation has no quota (unbounded LLM spend by any teacher account).

**Exam integrity (domain-specific).** Duration and end-date are not enforced at save/submit time; the countdown is client-clock based; auto-save failures are silent; no anti-cheat measures exist (no visibility detection, no navigation blocking, no session pinning); concurrent starts can duplicate attempts; `max_attempts` is nullified by `allow_retake`.

---

# 17. Performance Review

**Database queries.**
- **N+1 patterns throughout** — no `joinedload`/`selectinload` anywhere: teacher results (3 extra queries/row), student results (2/row), exam detail (1/question), profile enrollments (2/enrollment, in a block duplicated three times), dashboard exam lists, and the grading loop (1 query per MCQ response).
- In-memory pagination (fetch-all-then-slice) on teacher exams, student available-exams, and student materials — degrades linearly with table size regardless of page size.
- Unpaginated endpoints: admin classes, admin sections, teacher classes, class-section rosters.
- Redundant duplicate indexes (~8) add write overhead; two FK columns lack indexes (`classes.created_by`, `exam_results.reviewed_by`); expired sessions are never cleaned (function exists, unscheduled).
- Pool: `pool_size=10, max_overflow=20, pool_pre_ping=True`, no `pool_recycle`.

**API architecture.**
- All I/O is synchronous inside `async def` handlers — DB calls, Cloudinary upload/fetch, PDF/DOCX parsing, and the LLM call each **block the event loop**; one AI generation freezes every concurrent request on that worker.
- Uploads and download-proxies buffer entire files in memory (up to 50 MB per request; more before the size check rejects).
- AI calls have no timeout or `max_tokens` — worst-case request duration is unbounded.
- No caching of any kind (no HTTP cache headers, no server-side cache, no ETag).

**Frontend rendering.**
- Effectively a client-only SPA: 61/63 components `'use client'`, dashboards `ssr:false`, every guarded page renders a spinner until store hydration — guaranteed loading flash on each navigation; no server-side data fetching, no streaming, no Suspense boundaries (6 `useSearchParams` pages lack them).
- The exam timer re-renders the whole 523-line page every second; auto-save fires an API call **per keystroke** in textareas (no debounce).
- All 9 Inter font weights + italics are loaded; two raw `<img>` uses bypass `next/image`; `next.config.ts` defines no image/optimization settings.
- No route-level code-splitting beyond the three dynamic dashboards; large monolithic pages (15 files > 300 lines, max 1130).
- Client-side N+1: admin users and teacher students pages fetch the list, then one `getStudent` call per row.

**Potential bottlenecks (ranked).** 1) Event-loop blocking during AI generation; 2) N+1 + fetch-all pagination on results/exams as data grows; 3) memory-buffered file proxying under concurrent downloads; 4) per-keystroke auto-save storms during exams with many concurrent students; 5) unbounded prompt size (N materials × 60k chars) hitting provider limits/costs.

---

# 18. Existing AI Extension Points

Places where the current architecture already has seams AI could plug into (identification only — no design):

1. **Exam generation (existing, extendable).** `OpenAIService` + `ParserService` + the `/exams/generate` route form a working pipeline; the untyped `question_config` and the tolerant JSON parser are the obvious seams for richer generation controls. `question_bank` (table + model, currently an island) is a natural landing zone for generated-question reuse.
2. **Automated grading of text answers.** The grading engine already produces `is_correct=NULL` / 0 points for `short_answer`/`long_answer`, and `exam_results` carries never-used `reviewed_at`/`reviewed_by`/`feedback` columns — the schema slot for an AI (or AI-assisted human) review step already exists.
3. **Material understanding.** `ParserService.extract_text` is a general text-extraction utility invoked only by generation today; the same output could feed summaries, study aids, or Q&A over materials. (Gap: `doc`/image uploads are accepted but unparseable — an OCR/vision seam.)
4. **Results analytics.** `exam_results`, `exam_responses` (per-question correctness), difficulty labels on questions, and the teacher results endpoint provide the raw data for performance analytics, item analysis, and difficulty calibration; the admin dashboard's hardcoded `total_exams=0` and the placeholder "recent activity" panel are existing UI slots.
5. **Student guidance.** The student dashboard (upcoming exams, completed counts) and results detail (per-question breakdown) are the natural surfaces for AI feedback/study recommendations; `notifications` (table + model, unused) is the delivery mechanism already in the schema.
6. **Teacher assistance.** Exam creation forms (manual builder) could host question suggestions/improvement; the unused `QuestionBank.tags ARRAY` + GIN index anticipates semantic/tag retrieval.
7. **Admin reporting.** `audit_logs` (table + model, unused, JSONB details) is the schema seam for activity capture that any reporting/anomaly-detection layer would need.
8. **Scheduling.** `exams.start_date/end_date`, `exam_sections` (unused targeting), and the countdown UI exist; there is no scheduling intelligence today — purely a green field with data available.
9. **Proctoring/integrity signals.** The attempt lifecycle (`started_at`, auto-save stream, `time_spent_minutes`, statuses `timeout`/`abandoned` defined but unused) provides the event skeleton an integrity-analysis feature would consume.

---

# 19. Missing Features

**Missing business features (evidenced by schema/UI stubs):**
- Manual grading UI/endpoints for short/long answers (tri-state `is_correct` and reviewer columns exist; no code path writes them).
- Result-visibility enforcement (`exam_permissions` written, never read).
- Exam→section targeting (`exam_sections` never populated; exams are class-wide only).
- Question bank (table/model with tags exist; no endpoints, no UI).
- Notifications (table/model exist; no service, no UI).
- Password-reset delivery (no email integration; flow dead-ends).
- Google **sign-up** (login-only) and any self-registration.
- Teacher-class scoping (assignments recorded, unenforced).
- Admin password-reset for students that doesn't require the student's current password.
- Attempt timeout/abandonment handling (statuses defined, never set; no sweeper).

**Missing technical features:**
- Any test suite (backend `tests/` empty; frontend has no framework), any CI/CD, any deployment artifacts (Docker/compose/Procfile).
- Migration runner/tracking (hand-run SQL only; README omits migration 07).
- Background job processing (AI calls run in-request).
- Rate limiting / abuse protection; request logging; structured logging (prints only).
- Email sending of any kind.
- Server-side route protection on the frontend (`middleware.ts` absent); error boundaries (`error.tsx` absent); loading conventions (`loading.tsx` absent).
- API-client type safety (mutating methods typed `any`); shared Modal/hooks layers (hooks dir empty).
- Cloudinary object deletion on material delete; scheduled session cleanup.

**Missing architectural features:**
- Monitoring/observability: no metrics, no tracing, no error-reporting (Sentry etc.), no health check beyond a static 200 (no DB probe).
- Caching at any layer; pagination on several list endpoints; eager-loading strategy.
- A single source of truth for grading (currently 3 code paths + 1 SQL trigger) and for timezone policy (hardcoded −5h in 6 locations).

**Missing documentation:**
- Migration 07 in the migrations README; backend README and `.env.example` still describe the pre-migration Supabase/local-disk stack; no API changelog; no frontend README beyond the Next.js boilerplate; no architecture docs in-repo prior to this report (root `spec.md`/`update.md` cover two specific initiatives).

**Missing testing & monitoring:** covered above — both are absent in their entirety.

---

# 20. Architecture Summary

**Current architecture maturity: prototype-plus / pre-production MVP.** The system demonstrates a complete, working product loop with a well-organized backend and a thorough database design, but it has never been hardened: no tests, no CI, no deployment artifacts, no monitoring, and a set of enforcement gaps (teacher scoping, exam timing, result visibility) where the schema promises more than the code delivers.

**Current strengths.**
- Disciplined backend layering with clean role-based dependency injection and ORM-only data access.
- A relational schema notably more complete than the application (permissions, notifications, audit, question bank, section targeting) — the data model anticipates the product's future.
- One consistent frontend API gateway with working transparent token refresh.
- A functioning AI generation pipeline with real text extraction and provider flexibility (OpenAI/Gemini behind one SDK).

**Current limitations.**
- Trust boundaries are incomplete: client-side-only route guards, unenforced teacher↔class scoping, client-trusted exam timing, always-visible answer keys.
- Grading truth is fragmented across three Python sites and a divergent SQL trigger.
- Operational posture is weak: debug mode on, secrets in un-ignored backup files, plaintext token storage, verbose PII/answer logging, no rate limits, mixed error envelopes.
- Significant dead weight on both sides (stub routers, dead service, duplicate component folder, unused deps) raises the cost of safe change.

**Scalability assessment.** Adequate for a single institution with modest concurrency. Under growth it degrades predictably: N+1 queries and fetch-all pagination scale with data volume; synchronous LLM/file I/O inside the async loop caps concurrency at roughly one slow operation per worker; per-keystroke auto-save multiplies request volume during exams; memory-buffered 50 MB file proxying limits parallel downloads. Nothing is hostile to horizontal scaling (stateless API, external DB/storage), so scaling is achievable but only after the blocking-I/O and query patterns are addressed.

**Production readiness: not production-ready.** Blocking items visible in the codebase itself: zero tests, debug defaults, secret-bearing `.env.bak` outside `.gitignore`, non-functional password reset presented as functional, unenforced exam duration, no rate limiting, and dependency files that cannot reproduce a working install (`requirements.txt` missing runtime imports).

**Overall engineering quality.** Mixed but legible. The backend reads as the work of a developer with solid framework fluency and good instincts for layering, undermined by absent testing discipline and debug-era artifacts left in place. The frontend delivers a coherent, polished-looking UI while accumulating heavy duplication and forgoing nearly all of Next.js's server-side capabilities. The database layer is the most ambitious artifact — and the least connected, with roughly a quarter of its tables and several of its functions unreferenced by any application code. The dominant pattern across all three tiers is the same: **designed surface exceeds implemented behavior**, and the gap between them is precisely where most of the risk documented in this report lives.

---

*End of report. Compiled from direct inspection of every backend route/service/model/schema file, all seven SQL migrations, and the complete frontend `app/` tree (63 files). Endpoint count: 75. Table count: 20. Frontend routes: 22.*
