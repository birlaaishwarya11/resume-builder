# Resume Builder -- Public Deployment

## Project Structure

Flask app with blueprints at `app/`, templates at `templates/`, static at `static/`.

## How to Run

```bash
# Local development (requires PostgreSQL)
export DATABASE_URL=postgresql://user:pass@localhost:5432/resume_builder
export SECRET_KEY=dev-secret
flask --app app run --debug --port 5001

# Production (Railway)
# DATABASE_URL and SECRET_KEY are set via Railway environment
gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

## Key Architecture

- **Blueprints**: auth, editor, settings, databases, jd, cover_letter, versions, onboarding, parsers
- **Orchestrator** (`app/orchestrator.py`): Central coordinator for all agent/service calls
- **Agents** (`app/agents/`): 7-stage resume pipeline, cover letter, JD finder
- **Services** (`app/services/`): ai (LLM abstraction), resume (YAML CRUD), jd (analysis), parser, crypto
- **Database**: PostgreSQL only (no SQLite support)

## Agent Pipeline

JD paste triggers the 7-stage pipeline in `app/agents/jd_resume.py`:
1. Pre-screen (local, no LLM)
2. Version match (tag-based reuse)
3. Generator (LLM creates YAML)
4. PDF fit (WeasyPrint render + compression)
5. ATS verify (separate LLM scoring)
6. Improvement loop (iterate until score >= 90 AND 1 page)
7. Tag and save

## Data Directory

- `data/defaults/` -- Generic templates (no PII), copied to new users
- `data/{user_id}/` -- Per-user files (resume.yaml, databases, PDFs, versions)
- User data directories are gitignored

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| DATABASE_URL | Yes | PostgreSQL connection string |
| SECRET_KEY | Yes | Flask session secret |
| FERNET_KEY | Production | API key encryption key |
| DATA_DIR | No | User data directory (default: ./data) |
| PORT | No | Server port (default: 8000) |

## Testing

```bash
pytest tests/
```
