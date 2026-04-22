# Resume Builder -- Public Deployment

## Project Structure

Flask app with blueprints at `app/`, templates at `templates/`, static at `static/`.

## How to Run

```bash
# Local development (requires PostgreSQL or a Neon connection string)
export DATABASE_URL=postgresql://user:pass@localhost:5432/resume_builder
export SECRET_KEY=dev-secret
flask --app app run --debug --port 5001

# Production (Fly.io / Railway)
gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

## Key Architecture

- **Blueprints**: auth, editor, settings, databases, jd, cover_letter, versions, onboarding, parsers
- **Orchestrator** (`app/orchestrator.py`): Central coordinator for all agent/service calls
- **Agents** (`app/agents/`): 7-stage resume pipeline, cover letter, JD finder
- **Services** (`app/services/`): ai (LLM abstraction), resume (YAML CRUD), documents (per-user text in DB), jd (analysis), parser, crypto
- **Database**: PostgreSQL only -- **all per-user state lives here, no filesystem state**

## Storage model

All per-user content lives in Postgres. The `user_documents` table holds seven
TEXT columns per user (resume YAML, cover-letter draft, four markdown databases,
and the resume-learnings log). See `docs/adr/0001-postgres-only-storage.md` for
rationale. PDFs are rendered in-memory via WeasyPrint and streamed; they are
never persisted. `data/defaults/` ships read-only templates copied into a user's
documents at signup.

## Agent Pipeline

JD paste triggers the 7-stage pipeline in `app/agents/jd_resume.py`:
1. Pre-screen (local, no LLM)
2. Version match (tag-based reuse)
3. Generator (LLM creates YAML)
4. PDF fit (WeasyPrint render + compression, all in-memory)
5. ATS verify (separate LLM scoring)
6. Improvement loop (iterate until score >= 90 AND 1 page)
7. Tag and save

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| DATABASE_URL | Yes | PostgreSQL connection string |
| SECRET_KEY | Yes | Flask session secret |
| FERNET_KEY | Production | API key encryption key |
| PORT | No | Server port (default: 8000) |

## Testing

```bash
pytest tests/
```
