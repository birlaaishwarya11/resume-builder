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
- PostgreSQL 14+
- System libraries for WeasyPrint: pango, cairo, gdk-pixbuf

### Local Development

```bash
# Clone the repository
git clone <repo-url>
cd resume_builder

# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://localhost:5432/resume_builder"
export SECRET_KEY="your-secret-key-here"

# Initialize the database
python -c "from app import create_app; app = create_app(); app.app_context().__enter__()"

# Run the development server
flask run --debug --port 5000
```

Open http://localhost:5000 in your browser.

### macOS WeasyPrint Dependencies

```bash
brew install pango cairo gdk-pixbuf libffi
```

### Ubuntu/Debian WeasyPrint Dependencies

```bash
sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libcairo2 libffi-dev
```

## Railway Deployment

1. Connect your GitHub repository to Railway
2. Add a PostgreSQL plugin
3. Set the required environment variables (see below)
4. Deploy -- Railway will use the Procfile and Dockerfile automatically

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `SECRET_KEY` | Yes | Flask session signing key (use a long random string) |
| `PORT` | No | Server port (default: 5000, Railway sets this automatically) |
| `FLASK_ENV` | No | `development` or `production` (default: production) |

## Tech Stack

- **Backend**: Flask, Flask-Login, Flask-WTF, SQLAlchemy, bcrypt
- **Frontend**: Jinja2 templates, Ace.js editor, vanilla JavaScript
- **PDF rendering**: WeasyPrint
- **Database**: PostgreSQL with JSONB for tags
- **Deployment**: Railway (Dockerfile + Procfile), Gunicorn
- **Styling**: Custom CSS with split-pane layout, side panels, responsive design

## Project Structure

```
app/                    # Flask application package
  __init__.py           # App factory, blueprint registration
  auth.py               # Authentication blueprint
  editor.py             # Resume editor blueprint
  cover_letter.py       # Cover letter blueprint
  databases.py          # Markdown database editors
  settings.py           # User settings
  api.py                # JSON API endpoints
templates/              # Jinja2 templates
  base.html             # Base layout with nav
  editor.html           # Resume editor page
  cover_letter_editor.html
  onboarding.html       # Setup wizard
  ...
static/
  css/                  # Stylesheets
  js/                   # Client-side JavaScript
data/                   # User data directory
  defaults/             # Default database templates
tests/                  # Test suite
```
