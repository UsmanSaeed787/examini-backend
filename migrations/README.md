# Database Migrations

This directory contains SQL migration scripts for bootstrapping the Examini
database (PostgreSQL). After running these, Alembic manages all subsequent
schema changes.

## Migration order

Run these in your database's SQL editor (e.g. [Neon](https://neon.tech)
SQL Editor), **in order**:

1. `01_create_extensions.sql` — Enable required PostgreSQL extensions (uuid-ossp)
2. `02_create_tables.sql` — Create all core tables (users, classes, exams, questions, etc.)
3. `03_create_indexes.sql` — Create indexes for performance
4. `04_create_functions_triggers.sql` — Create database functions and triggers (updated_at, etc.)
5. **Skip `05_setup_rls_policies.sql`** — It uses Supabase-only `auth.uid()`; all access control is enforced in FastAPI regardless
6. `06_seed_initial_data.sql` — Seed initial admin user (update password hash first — see below)
7. `07_add_student_profiles_and_roll_numbers.sql` — Student profiles and roll number support

Then apply Alembic migrations for the AI layer and any later changes:

```bash
cd backend
uv run alembic upgrade head
```

Alembic covers migrations `08` onwards (AI tables, assessment workflows,
agent state, memories, workflow generations, adjusted checkpoints).

## How to run

### Option 1: Neon SQL Editor (recommended)

1. Go to your [Neon](https://neon.tech) project dashboard
2. Open the SQL Editor
3. Copy and paste each migration file's content
4. Execute in order: `01` → `04`, `06`, `07`
5. Then run `uv run alembic upgrade head` from the `backend/` directory

### Option 2: psql command line

```bash
export DATABASE_URL="postgresql://user:pass@host/db"

psql $DATABASE_URL -f 01_create_extensions.sql
psql $DATABASE_URL -f 02_create_tables.sql
psql $DATABASE_URL -f 03_create_indexes.sql
psql $DATABASE_URL -f 04_create_functions_triggers.sql
# Skip 05 — Supabase-only RLS
psql $DATABASE_URL -f 06_seed_initial_data.sql
psql $DATABASE_URL -f 07_add_student_profiles_and_roll_numbers.sql

cd ..
uv run alembic upgrade head
```

## Password hash for the seed admin

`06_seed_initial_data.sql` contains a **placeholder** password hash.
Generate a real bcrypt hash before using it:

```bash
cd backend
uv run python -c "from app.utils.security import get_password_hash; print(get_password_hash('your-password'))"
```

Update the hash in the SQL file or directly in the database row, then sign
in as admin.

## Migration inventory

| File | Purpose |
|---|---|
| `01_create_extensions.sql` | PostgreSQL extensions (uuid-ossp) |
| `02_create_tables.sql` | Core tables: users, classes, sections, exams, questions, materials, attempts, etc. |
| `03_create_indexes.sql` | Performance indexes |
| `04_create_functions_triggers.sql` | Functions & triggers (updated_at, etc.) |
| `05_setup_rls_policies.sql` | ~~Supabase RLS policies~~ — **skip** |
| `06_seed_initial_data.sql` | Initial admin user seed |
| `07_add_student_profiles_and_roll_numbers.sql` | Student profiles, roll numbers |
| `08_create_ai_tables.sql` | AI tool/agent registry tables |
| `09_create_assessment_workflow_tables.sql` | Assessment workflow state |
| `10_create_agent_state.sql` | Agent execution state |
| `11_create_ai_memories.sql` | Agent memory persistence |
| `12_create_workflow_generations.sql` | Workflow generation tracking |
| `13_allow_adjusted_checkpoints.sql` | Adjusted checkpoint support |

## Troubleshooting

| Problem | Solution |
|---|---|
| Foreign key errors | Ensure tables are created in the correct order (01 → 04) |
| `A database error occurred` in the app | Run `uv run alembic upgrade head` to apply pending migrations |
| Special characters break `DATABASE_URL` | Run `uv run python fix_database_url.py` |
| Index creation fails | Verify that the referenced tables exist first |
