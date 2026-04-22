# Resume Builder

A Flask web application for creating, editing, and tailoring resumes using a YAML-based editor with live preview. Includes JD matching, ATS scoring, cover letter generation, and version history.

## Features

- **Split-pane editor**: Ace.js YAML editor on the left, live 8.5" x 11" resume preview on the right
- **PDF resume parsing**: Upload an existing PDF resume and convert it to editable YAML
- **JD matching**: Paste a job description, search by company+role, or provide a URL to tailor your resume
- **ATS scoring**: Automated scoring (keyword match, skills alignment, experience relevance, quantified achievements)
- **One-page fitting**: Automatic compression pipeline to fit resumes to a single page
- **Version history**: Browse and restore previous resume versions with tags and labels
- **Cover letter editor**: Generate and edit cover letters with live preview
- **Markdown databases**: Edit candidate database, resume rules, cover letter database, and cover letter rules
- **Theme-based tagging**: Auto-tag resumes with categories like backend, devops, ai-engineer, fintech

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 14+ (or a managed Postgres like [Neon](https://neon.tech))
- System libraries for WeasyPrint: pango, cairo, gdk-pixbuf

### Local Development

```bash
git clone <repo-url>
cd resume_builder

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql://localhost:5432/resume_builder"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

flask --app app run --debug --port 5001
```

Open http://localhost:5001 in your browser. Schema is created automatically on first request.

### macOS WeasyPrint Dependencies

```bash
brew install pango cairo gdk-pixbuf libffi
```

### Ubuntu/Debian WeasyPrint Dependencies

```bash
sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libcairo2 libffi-dev
```

## Deployment (free tier: Fly.io + Neon)

**Signup:**
1. [Neon](https://console.neon.tech/signup) -- serverless Postgres (0.5 GB free, auto-suspend).
2. [Fly.io](https://fly.io/app/sign-up) -- 3 shared-cpu-1x VMs free.

**Steps:**
```bash
# 1. Install flyctl
brew install flyctl
fly auth login

# 2. In Neon dashboard, create a project, copy the POOLED connection string
#    (hostname ends with "-pooler"). Example:
#    postgresql://user:pw@ep-xxx-pooler.region.neon.tech/neondb

# 3. Launch the Fly app (picks up the Dockerfile)
fly launch --no-deploy
# Say "no" when asked to add a Postgres -- we use Neon.

# 4. Set secrets
fly secrets set \
  DATABASE_URL='<your-neon-pooled-url>' \
  SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

# 5. Deploy
fly deploy
```

No volume, no `DATA_DIR`. All per-user state lives in Postgres (see
`docs/adr/0001-postgres-only-storage.md`).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (Neon pooled URL in prod) |
| `SECRET_KEY` | Yes | Flask session signing key (use a long random string) |
| `FERNET_KEY` | Production | Key for encrypting user-stored AI API keys |
| `PORT` | No | Server port (Fly/Railway set this automatically) |

## Tech Stack

- **Backend**: Flask, psycopg2, WeasyPrint
- **Frontend**: Jinja2, Ace.js, vanilla JavaScript
- **Database**: PostgreSQL -- single source of truth for all per-user state
- **Deployment**: Fly.io (recommended free tier) or Railway; Dockerfile + Gunicorn
- **Styling**: Custom CSS with split-pane layout

## Project Structure

```
app/
  __init__.py             # App factory, blueprint registration
  config.py               # Environment config
  models.py               # Postgres schema + CRUD
  orchestrator.py         # Central coordinator for agent/service calls
  agents/                 # LLM-backed agents (jd_resume, cover_letter, jd_finder)
  blueprints/             # Flask blueprints (auth, editor, databases, jd, ...)
  services/               # ai, documents, resume, jd, parser, crypto
  parsers/                # PDF parsing (local + LLM-assisted)
templates/                # Jinja2 templates
static/                   # CSS + client-side JS
data/
  defaults/               # Read-only templates shipped with the app
docs/
  adr/                    # Architecture Decision Records
tests/
```

## Architecture notes

- **No per-user filesystem state.** All YAML, markdown databases, rules,
  the agent learning log, and the cover-letter draft live in Postgres
  `user_documents`. See [docs/adr/0001-postgres-only-storage.md](docs/adr/0001-postgres-only-storage.md).
- **PDFs are ephemeral.** Generated in-memory by WeasyPrint and streamed
  to the client.
- **The 7-stage JD agent pipeline** is orchestrated in
  `app/agents/jd_resume.py`: pre-screen -> version match -> generator ->
  PDF fit -> ATS verify -> improvement loop -> tag/save.
