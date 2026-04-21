# Architecture

## System Overview

Resume Builder is a Flask web application with a split-pane YAML editor and live resume preview. Users upload a PDF resume, which is parsed to YAML, then edit and tailor it for specific job descriptions. A multi-stage JD pipeline analyzes job postings, generates tailored resumes, fits them to one page, and verifies ATS compatibility.

## Blueprint Structure

```
app/
  __init__.py          # create_app(), register blueprints
  auth.py              # login, signup, logout, session management
  editor.py            # resume editor page, preview rendering
  cover_letter.py      # cover letter editor and generation
  databases.py         # candidate DB, resume rules, CL rules, CL DB editors
  settings.py          # user preferences (font, margins, style)
  api.py               # JSON API endpoints (save, preview, parse, JD analyze/generate/find, versions, tags)
```

Each blueprint is registered with a URL prefix:
- `/auth` -- authentication
- `/editor` (or `/`) -- main resume editor
- `/cover-letter` -- cover letter editor
- `/databases` -- markdown database editors
- `/settings` -- user settings
- `/api` -- all AJAX/fetch endpoints

## Data Flow: JD-to-Resume Pipeline

```
User pastes JD (or provides company+role / URL)
        |
        v
   [1] JD Extraction
        |  - Paste: use text directly
        |  - Company+role: web search -> fetch page -> extract JD
        |  - URL: fetch page -> extract JD
        v
   [2] Pre-screen
        |  - Check for hard blockers (citizenship, clearance)
        |  - Warn user if blockers found
        v
   [3] Read Source Files
        |  - candidate_database.md (ground truth)
        |  - resume_rules.md (formatting rules)
        |  - resume_learnings.md (past user edit patterns)
        v
   [4] Generate YAML
        |  - Follow section structure and bullet rules
        |  - Prioritize by JD relevance
        |  - Full natural English (no abbreviations on first pass)
        v
   [5] Render PDF + Page Check
        |  - WeasyPrint renders HTML to PDF
        |  - Count pages; if > 1, compress
        v
   [6] ATS Verification
        |  - Score: keyword match (40%), skills alignment (25%),
        |    experience relevance (20%), quantified achievements (15%)
        |  - If score < 90, integrate missing keywords
        |  - Re-check page count after changes
        |  - Max 3 iterations
        v
   [7] Tag + Report
        |  - Auto-tag with theme-based tags (backend, devops, ai-engineer, etc.)
        |  - Return ATS score, tags, assessment to UI
        v
   Editor updated, preview refreshed
```

## Database Schema

Five tables in PostgreSQL:

### users
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| email | VARCHAR(255) UNIQUE | |
| password_hash | VARCHAR(255) | bcrypt |
| created_at | TIMESTAMP | DEFAULT now() |

### resumes
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | INT FK -> users | |
| yaml_content | TEXT | Current active resume |
| style | VARCHAR(50) | DEFAULT 'classic' |
| updated_at | TIMESTAMP | |

### resume_versions
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | INT FK -> users | |
| yaml_content | TEXT | Snapshot |
| label | VARCHAR(255) | e.g. "JD Agent: Backend" |
| source | VARCHAR(50) | 'manual', 'jd_agent', 'import' |
| tags | JSONB | ["backend", "fintech"] |
| ats_score | INT | 0-100 |
| created_at | TIMESTAMP | DEFAULT now() |

### cover_letters
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | INT FK -> users | |
| draft_yaml | TEXT | Current draft |
| company | VARCHAR(255) | |
| role | VARCHAR(255) | |
| created_at | TIMESTAMP | |

### user_databases
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| user_id | INT FK -> users | |
| db_type | VARCHAR(50) | 'candidate', 'resume_rules', 'cl_db', 'cl_rules', 'learnings' |
| content | TEXT | Markdown content |
| updated_at | TIMESTAMP | |

## Security Model

- **Authentication**: Flask-Login with bcrypt password hashing.
- **Sessions**: Server-side, signed with `SECRET_KEY`. Session cookie is HttpOnly, Secure (in production), SameSite=Lax.
- **Authorization**: All API endpoints check `current_user.id` matches the requested resource. Users can only access their own data.
- **CSRF**: Flask-WTF CSRF protection on all form submissions. API endpoints validate the session.
- **Input validation**: YAML content is parsed with `yaml.safe_load()` before processing. File uploads validated for type and size.
- **Secrets**: All secrets (SECRET_KEY, DATABASE_URL) are loaded from environment variables, never committed.
- **PDF rendering**: WeasyPrint runs in a sandboxed context. No user-supplied CSS or JavaScript is executed server-side.

## Orchestrator Pattern

The JD pipeline uses an orchestrator pattern rather than chained microservices:

1. A single `process_jd()` function in `api.py` coordinates the 7-stage pipeline.
2. Each stage is a pure function that takes inputs and returns outputs (no side effects except stage 4 which writes files).
3. The orchestrator handles retries (max 3 iterations for ATS score improvement) and early termination (hard blockers in pre-screen).
4. All stages run in the same process; no message queues or service-to-service calls.

This keeps the system simple and debuggable while maintaining clear separation of concerns.

## Deployment on Railway

The application deploys on Railway with:

- **Procfile**: `web: gunicorn app:create_app() --bind 0.0.0.0:$PORT`
- **railway.toml**: Build and deploy configuration
- **PostgreSQL plugin**: Provisioned automatically; `DATABASE_URL` injected as env var
- **Persistent storage**: User-uploaded files stored in `/data` volume (or S3 in production)
- **Health check**: `GET /auth/login` returns 200

The Dockerfile installs system dependencies for WeasyPrint (pango, cairo, gdk-pixbuf) and Python dependencies from `requirements.txt`.
