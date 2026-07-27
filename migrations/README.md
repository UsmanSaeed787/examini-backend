# Database Migrations

This directory contains SQL migration scripts for setting up the exam management system database in Supabase (PostgreSQL).

## Migration Order

Execute these migrations in the Supabase SQL Editor in the following order:

1. `01_create_extensions.sql` - Enable required PostgreSQL extensions
2. `02_create_tables.sql` - Create all database tables
3. `03_create_indexes.sql` - Create indexes for performance
4. `04_create_functions_triggers.sql` - Create database functions and triggers
5. `05_setup_rls_policies.sql` - Enable Row Level Security
6. `06_seed_initial_data.sql` - Seed initial admin user (optional, can be done after backend setup)

## How to Run Migrations

### Option 1: Using Supabase SQL Editor

1. Go to your Supabase project dashboard
2. Navigate to SQL Editor
3. Copy and paste each migration file's content
4. Execute in order (01 → 02 → 03 → 04 → 05 → 06)
5. Verify all tables are created successfully

### Option 2: Using psql Command Line

```bash
# Set your database connection string
export DATABASE_URL="postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"

# Run migrations in order
psql $DATABASE_URL -f 01_create_extensions.sql
psql $DATABASE_URL -f 02_create_tables.sql
psql $DATABASE_URL -f 03_create_indexes.sql
psql $DATABASE_URL -f 04_create_functions_triggers.sql
psql $DATABASE_URL -f 05_setup_rls_policies.sql
# Skip 06_seed_initial_data.sql until backend is set up to generate proper password hash
```

## Important Notes

- **Password Hash**: The seed script (`06_seed_initial_data.sql`) contains a placeholder password hash. You must generate the actual bcrypt hash using the backend authentication system before running this migration in production.

- **RLS Policies**: Row Level Security is enabled, but detailed policies will be managed through the backend application using JWT tokens and role-based access control.

- **Backup**: Always backup your database before running migrations in production.

## Verification

After running all migrations, verify:

1. All tables exist: Check in Supabase Table Editor
2. Indexes are created: Query `pg_indexes` to verify
3. Triggers are active: Check triggers on tables
4. Functions exist: Query `pg_proc` to verify
5. RLS is enabled: Check table RLS status

## Troubleshooting

- If you encounter foreign key errors, ensure tables are created in the correct order
- If indexes fail, check that tables exist first
- If RLS blocks queries, use service_role key for initial setup
- Check Supabase logs for detailed error messages

