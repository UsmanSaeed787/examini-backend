# Exam Management System - Backend API

FastAPI backend for the Exam Management System.

## Setup

### 1. Install Dependencies

Using uv (recommended):
```bash
cd backend
uv sync
```

Or using pip:
```bash
cd backend
pip install -r requirements.txt
```

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in your values:
```bash
cp .env.example .env
```

Update the following:
- `DATABASE_URL`: Your Supabase PostgreSQL connection string
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`: From Supabase dashboard
- `JWT_SECRET_KEY`: Generate a strong secret key (min 32 chars)
- `OPENAI_API_KEY`: Your OpenAI API key (if using exam generation)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: For Google OAuth (optional)

### 3. Database Setup

Run the migrations in `migrations/` directory using Supabase SQL Editor:
1. `01_create_extensions.sql`
2. `02_create_tables.sql`
3. `03_create_indexes.sql`
4. `04_create_functions_triggers.sql`
5. `05_setup_rls_policies.sql`
6. `06_seed_initial_data.sql` (update with actual password hash)

### 4. Run the Server

```bash
# Using uv
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Using python
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration
│   ├── database.py          # Database connection
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic schemas
│   ├── api/                 # API routes
│   ├── services/            # Business logic
│   ├── middleware/          # Middleware (error handling)
│   └── utils/               # Utility functions
├── migrations/              # Database migrations
├── tests/                   # Test files
└── requirements.txt        # Dependencies
```

## Features

- JWT-based authentication
- Role-based access control (Admin, Teacher, Student)
- User management
- Class and section management
- Material upload/download
- Exam creation and management
- OpenAI-powered exam generation
- Automatic result calculation
- Result visibility controls

## Development

Run with auto-reload:
```bash
uvicorn app.main:app --reload
```

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=app
```

## Production

1. Set `DEBUG=False` in `.env`
2. Use a production WSGI server (e.g., Gunicorn)
3. Set up proper CORS origins
4. Use environment variables for all secrets
5. Enable HTTPS
6. Set up logging and monitoring

