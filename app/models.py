"""Database models and queries -- PostgreSQL only.

All per-user state lives in the database. No filesystem storage of user data.
Application-level assets (templates, default markdown) ship with the app under
`data/defaults/` and are read once at signup to seed a new user's documents.
"""

import json
import os
import secrets
from datetime import datetime

import psycopg2
import psycopg2.extras
import psycopg2.errors
from werkzeug.security import generate_password_hash, check_password_hash

from app.config import Config

DATABASE_URL = Config.DATABASE_URL

DEFAULT_SECTION_NAMES = {
    "education": "Education",
    "technical_skills": "Skills",
    "experience": "Experience",
    "projects": "Projects",
    "extracurricular": "Extracurricular",
}

_OLD_SECTION_NAMES_JSON = json.dumps({
    "education": "EDUCATION",
    "technical_skills": "TECHNICAL SKILLS",
    "experience": "PROFESSIONAL EXPERIENCE",
    "projects": "PROJECTS AND HACKATHON HIGHLIGHTS",
    "extracurricular": "EXTRACURRICULAR ACTIVITIES / VOLUNTEER & RESEARCH PAPERS",
})


# Per-user document fields stored in the user_documents table.
DOCUMENT_FIELDS = (
    'resume_yaml',
    'cover_letter_draft_yaml',
    'candidate_database',
    'resume_rules',
    'cover_letter_database',
    'cover_letter_rules',
    'resume_learnings',
)

# Which default template file seeds which user_documents field at signup.
_DEFAULT_SEEDS = {
    'candidate_database': 'candidate_database.md',
    'resume_rules': 'resume_rules.md',
    'cover_letter_database': 'cover_letter_database.md',
    'cover_letter_rules': 'cover_letter_rules.md',
}

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULTS_DIR = os.path.join(_PROJECT_ROOT, 'data', 'defaults')


def _read_default(filename: str) -> str:
    path = os.path.join(_DEFAULTS_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    title = filename.replace('_', ' ').replace('.md', '').title()
    return f"# {title}\n\nAdd your content here.\n"


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_db():
    """Return a new PostgreSQL connection."""
    return psycopg2.connect(DATABASE_URL)


def _fetchone(conn, query, params=()):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def _fetchall(conn, query, params=()):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def _execute(conn, query, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    cur.close()


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

def init_db():
    """Create tables and run migrations (idempotent).

    Guarded by a Postgres advisory lock so that multi-worker servers
    (e.g. gunicorn --workers N) don't race on CREATE TABLE IF NOT EXISTS,
    which doesn't itself lock the pg_class catalog.
    """
    conn = get_db()
    cur = conn.cursor()
    # Arbitrary bigint key -- all workers use the same one.
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (726154_8321_42,))

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE,
            mcp_api_key TEXT DEFAULT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            header_json TEXT NOT NULL DEFAULT '{}',
            section_names_json TEXT NOT NULL DEFAULT '{}',
            custom_sections_json TEXT NOT NULL DEFAULT '[]',
            style_json TEXT NOT NULL DEFAULT '{}',
            ai_provider TEXT DEFAULT NULL,
            ai_api_key_encrypted TEXT DEFAULT NULL,
            ai_model TEXT DEFAULT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_documents (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            resume_yaml             TEXT NOT NULL DEFAULT '',
            cover_letter_draft_yaml TEXT NOT NULL DEFAULT '',
            candidate_database      TEXT NOT NULL DEFAULT '',
            resume_rules            TEXT NOT NULL DEFAULT '',
            cover_letter_database   TEXT NOT NULL DEFAULT '',
            cover_letter_rules      TEXT NOT NULL DEFAULT '',
            resume_learnings        TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS parsers (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'DRAFT',
            label TEXT DEFAULT NULL,
            source_pdf_hash TEXT DEFAULT NULL,
            coverage_score REAL DEFAULT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS resume_versions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            yaml_content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual_edit',
            label TEXT DEFAULT NULL,
            tags TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS jd_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            jd_text TEXT NOT NULL,
            match_score INTEGER DEFAULT NULL,
            suggestions_json TEXT NOT NULL DEFAULT '[]',
            applied_version_id INTEGER DEFAULT NULL
                REFERENCES resume_versions(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            user_name TEXT NOT NULL,
            feedback TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    _safe_add_column(cur, 'users', 'mcp_api_key', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'user_settings', 'ai_provider', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'user_settings', 'ai_api_key_encrypted', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'user_settings', 'ai_model', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'resume_versions', 'tags', 'TEXT DEFAULT NULL')

    cur.execute(
        "UPDATE user_settings SET section_names_json = %s WHERE section_names_json = %s",
        (json.dumps(DEFAULT_SECTION_NAMES), _OLD_SECTION_NAMES_JSON),
    )
    conn.commit()
    cur.close()
    conn.close()


def _safe_add_column(cur, table, column, definition):
    try:
        cur.execute("SAVEPOINT add_col")
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        cur.execute("RELEASE SAVEPOINT add_col")
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT add_col")
        cur.execute("RELEASE SAVEPOINT add_col")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(name, email, password):
    """Create a new user. Returns user_id or None if email is taken."""
    conn = get_db()
    pw_hash = generate_password_hash(password)
    try:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO users (email, password_hash, name, created_at) '
            'VALUES (%s, %s, %s, %s) RETURNING id',
            (email, pw_hash, name, datetime.now().isoformat()),
        )
        user_id = cur.fetchone()[0]
        cur.close()

        default_header = {
            "name": name,
            "contact": {
                "location": "",
                "phone": "",
                "email": email,
                "github": "",
                "linkedin": "",
                "portfolio_label": "Portfolio",
                "portfolio_url": "",
            },
        }
        _execute(
            conn,
            'INSERT INTO user_settings '
            '(user_id, header_json, section_names_json, custom_sections_json, style_json) '
            'VALUES (%s, %s, %s, %s, %s)',
            (user_id, json.dumps(default_header), json.dumps(DEFAULT_SECTION_NAMES), '[]', '{}'),
        )

        seed_values = {field: _read_default(fname) for field, fname in _DEFAULT_SEEDS.items()}
        _execute(
            conn,
            '''INSERT INTO user_documents
               (user_id, candidate_database, resume_rules,
                cover_letter_database, cover_letter_rules, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s)''',
            (
                user_id,
                seed_values['candidate_database'],
                seed_values['resume_rules'],
                seed_values['cover_letter_database'],
                seed_values['cover_letter_rules'],
                datetime.now().isoformat(),
            ),
        )

        conn.commit()
        conn.close()
        return user_id
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        conn.close()
        return None
    except Exception:
        conn.rollback()
        conn.close()
        raise


def authenticate_user(email, password):
    conn = get_db()
    user = _fetchone(conn, 'SELECT * FROM users WHERE email = %s', (email,))
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None


def verify_user_password(user_id, password):
    conn = get_db()
    user = _fetchone(conn, 'SELECT password_hash FROM users WHERE id = %s', (user_id,))
    conn.close()
    return bool(user and check_password_hash(user['password_hash'], password))


def get_user_by_id(user_id):
    conn = get_db()
    user = _fetchone(
        conn, 'SELECT id, email, name, created_at FROM users WHERE id = %s', (user_id,),
    )
    conn.close()
    return user


def delete_user(user_id):
    """Delete a user account. Cascades to settings, documents, versions, sessions."""
    conn = get_db()
    _execute(conn, 'DELETE FROM users WHERE id = %s', (user_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

def get_user_settings(user_id):
    conn = get_db()
    row = _fetchone(conn, 'SELECT * FROM user_settings WHERE user_id = %s', (user_id,))
    conn.close()
    if row:
        return {
            "header": json.loads(row['header_json']),
            "section_names": json.loads(row['section_names_json']),
            "custom_sections": json.loads(row.get('custom_sections_json') or '[]'),
            "style": json.loads(row.get('style_json') or '{}'),
        }
    return {
        "header": {"name": "", "contact": {}},
        "section_names": DEFAULT_SECTION_NAMES.copy(),
        "custom_sections": [],
        "style": {},
    }


def update_user_settings(user_id, header=None, section_names=None,
                         custom_sections=None, style=None):
    conn = get_db()
    current = get_user_settings(user_id)
    if header is not None:
        current["header"] = header
    if section_names is not None:
        current["section_names"] = section_names
    if custom_sections is not None:
        current["custom_sections"] = custom_sections
    if style is not None:
        current["style"] = style

    _execute(
        conn,
        '''INSERT INTO user_settings
           (user_id, header_json, section_names_json, custom_sections_json, style_json)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT(user_id) DO UPDATE SET
             header_json = excluded.header_json,
             section_names_json = excluded.section_names_json,
             custom_sections_json = excluded.custom_sections_json,
             style_json = excluded.style_json''',
        (user_id, json.dumps(current["header"]), json.dumps(current["section_names"]),
         json.dumps(current["custom_sections"]), json.dumps(current["style"])),
    )
    conn.commit()
    conn.close()


def save_user_api_config(user_id, provider, api_key_encrypted, model=None):
    conn = get_db()
    _execute(
        conn,
        'UPDATE user_settings SET ai_provider = %s, ai_api_key_encrypted = %s, ai_model = %s '
        'WHERE user_id = %s',
        (provider or None, api_key_encrypted or None, model or None, user_id),
    )
    conn.commit()
    conn.close()


def get_user_api_config(user_id):
    conn = get_db()
    row = _fetchone(
        conn,
        'SELECT ai_provider, ai_api_key_encrypted, ai_model FROM user_settings WHERE user_id = %s',
        (user_id,),
    )
    conn.close()
    if row and row.get('ai_api_key_encrypted'):
        return {
            'provider': row['ai_provider'],
            'ai_api_key_encrypted': row['ai_api_key_encrypted'],
            'model': row['ai_model'],
        }
    return None


def delete_user_api_config(user_id):
    conn = get_db()
    _execute(
        conn,
        'UPDATE user_settings SET ai_provider = NULL, ai_api_key_encrypted = NULL, ai_model = NULL '
        'WHERE user_id = %s',
        (user_id,),
    )
    conn.commit()
    conn.close()


def is_onboarding_complete(user_id):
    conn = get_db()
    row = _fetchone(conn, 'SELECT onboarding_complete FROM users WHERE id = %s', (user_id,))
    conn.close()
    return bool(row and row['onboarding_complete'])


def mark_onboarding_complete(user_id):
    conn = get_db()
    _execute(conn, 'UPDATE users SET onboarding_complete = TRUE WHERE id = %s', (user_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# User documents
# ---------------------------------------------------------------------------

def _ensure_documents_row(conn, user_id: int):
    """Create an empty user_documents row if one doesn't exist."""
    _execute(
        conn,
        '''INSERT INTO user_documents (user_id, updated_at)
           VALUES (%s, %s)
           ON CONFLICT(user_id) DO NOTHING''',
        (user_id, datetime.now().isoformat()),
    )


def get_document(user_id: int, field: str) -> str:
    """Return the text content for a single document field. Empty string if unset."""
    if field not in DOCUMENT_FIELDS:
        raise ValueError(f"Unknown document field: {field}")
    conn = get_db()
    row = _fetchone(
        conn,
        f'SELECT {field} AS content FROM user_documents WHERE user_id = %s',
        (user_id,),
    )
    conn.close()
    return (row['content'] if row else '') or ''


def save_document(user_id: int, field: str, content: str) -> None:
    """Write a document field. Creates the row if missing."""
    if field not in DOCUMENT_FIELDS:
        raise ValueError(f"Unknown document field: {field}")
    conn = get_db()
    _ensure_documents_row(conn, user_id)
    _execute(
        conn,
        f'UPDATE user_documents SET {field} = %s, updated_at = %s WHERE user_id = %s',
        (content or '', datetime.now().isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def get_all_documents(user_id: int) -> dict:
    """Return all document fields as a dict. Missing row yields empty strings."""
    conn = get_db()
    row = _fetchone(
        conn,
        'SELECT ' + ', '.join(DOCUMENT_FIELDS) + ' FROM user_documents WHERE user_id = %s',
        (user_id,),
    )
    conn.close()
    if not row:
        return {f: '' for f in DOCUMENT_FIELDS}
    return {f: (row.get(f) or '') for f in DOCUMENT_FIELDS}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def save_feedback(user_id: int, user_name: str, feedback: str) -> None:
    conn = get_db()
    _execute(
        conn,
        'INSERT INTO feedback (user_id, user_name, feedback, created_at) '
        'VALUES (%s, %s, %s, %s)',
        (user_id, user_name, feedback, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# MCP API keys
# ---------------------------------------------------------------------------

def generate_mcp_api_key(user_id):
    key = secrets.token_urlsafe(32)
    conn = get_db()
    _execute(conn, 'UPDATE users SET mcp_api_key = %s WHERE id = %s', (key, user_id))
    conn.commit()
    conn.close()
    return key


def get_user_by_mcp_key(api_key):
    if not api_key:
        return None
    conn = get_db()
    user = _fetchone(conn, 'SELECT id, email, name FROM users WHERE mcp_api_key = %s', (api_key,))
    conn.close()
    return user


def get_mcp_api_key(user_id):
    conn = get_db()
    row = _fetchone(conn, 'SELECT mcp_api_key FROM users WHERE id = %s', (user_id,))
    conn.close()
    return row['mcp_api_key'] if row else None


# ---------------------------------------------------------------------------
# Parsers (DRAFT -> ACTIVE -> LOCKED)
# ---------------------------------------------------------------------------

PARSER_STATES = ('DRAFT', 'ACTIVE', 'LOCKED')


def create_parser(user_id, code, state='DRAFT', label=None,
                  source_pdf_hash=None, coverage_score=None):
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO parsers '
        '(user_id, code, state, label, source_pdf_hash, coverage_score, created_at, updated_at) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
        (user_id, code, state, label, source_pdf_hash, coverage_score, now, now),
    )
    parser_id = cur.fetchone()[0]
    cur.close()
    conn.commit()
    conn.close()
    return parser_id


def get_parser_by_id(parser_id):
    conn = get_db()
    row = _fetchone(conn, 'SELECT * FROM parsers WHERE id = %s', (parser_id,))
    conn.close()
    return row


def get_active_parser(user_id):
    conn = get_db()
    row = _fetchone(
        conn,
        "SELECT * FROM parsers WHERE user_id = %s AND state = 'LOCKED' "
        "ORDER BY updated_at DESC LIMIT 1",
        (user_id,),
    )
    if not row:
        row = _fetchone(
            conn,
            "SELECT * FROM parsers WHERE user_id = %s AND state = 'ACTIVE' "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        )
    conn.close()
    return row


def get_draft_parser(user_id):
    conn = get_db()
    row = _fetchone(
        conn,
        "SELECT * FROM parsers WHERE user_id = %s AND state = 'DRAFT' "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    conn.close()
    return row


def list_parsers(user_id):
    conn = get_db()
    rows = _fetchall(
        conn,
        'SELECT id, user_id, state, label, source_pdf_hash, coverage_score, '
        'created_at, updated_at FROM parsers WHERE user_id = %s ORDER BY created_at DESC',
        (user_id,),
    )
    conn.close()
    return rows


def update_parser_state(parser_id, state):
    if state not in PARSER_STATES:
        raise ValueError(f"Invalid parser state: {state}. Must be one of {PARSER_STATES}")
    now = datetime.now().isoformat()
    conn = get_db()
    _execute(conn, 'UPDATE parsers SET state = %s, updated_at = %s WHERE id = %s',
             (state, now, parser_id))
    conn.commit()
    conn.close()


def update_parser_code(parser_id, code, coverage_score=None):
    now = datetime.now().isoformat()
    conn = get_db()
    _execute(conn, 'UPDATE parsers SET code = %s, coverage_score = %s, updated_at = %s WHERE id = %s',
             (code, coverage_score, now, parser_id))
    conn.commit()
    conn.close()


def lock_parser(user_id, parser_id):
    now = datetime.now().isoformat()
    conn = get_db()
    _execute(
        conn,
        "UPDATE parsers SET state = 'ACTIVE', updated_at = %s "
        "WHERE user_id = %s AND state = 'LOCKED' AND id != %s",
        (now, user_id, parser_id),
    )
    _execute(
        conn,
        "UPDATE parsers SET state = 'LOCKED', updated_at = %s WHERE id = %s AND user_id = %s",
        (now, parser_id, user_id),
    )
    conn.commit()
    conn.close()


def delete_parser(parser_id, user_id):
    conn = get_db()
    _execute(conn, 'DELETE FROM parsers WHERE id = %s AND user_id = %s', (parser_id, user_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Resume versions
# ---------------------------------------------------------------------------

RESUME_SOURCES = ('upload', 'manual_edit', 'jd_applied', 'ai_edit', 'jd_agent')


def save_resume_version(user_id, yaml_content, source='manual_edit', label=None, tags=None):
    if source not in RESUME_SOURCES:
        source = 'manual_edit'
    tags_json = json.dumps(tags) if tags else None
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO resume_versions (user_id, yaml_content, source, label, tags, created_at) '
        'VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
        (user_id, yaml_content, source, label, tags_json, now),
    )
    version_id = cur.fetchone()[0]
    cur.close()
    conn.commit()
    conn.close()
    return version_id


def list_resume_versions(user_id):
    conn = get_db()
    rows = _fetchall(
        conn,
        'SELECT id, user_id, source, label, tags, created_at FROM resume_versions '
        'WHERE user_id = %s ORDER BY created_at DESC',
        (user_id,),
    )
    conn.close()
    return rows


def update_version_tags(version_id, user_id, tags):
    tags_json = json.dumps(tags) if tags else None
    conn = get_db()
    _execute(conn, 'UPDATE resume_versions SET tags = %s WHERE id = %s AND user_id = %s',
             (tags_json, version_id, user_id))
    conn.commit()
    conn.close()


def get_resume_version(version_id, user_id):
    conn = get_db()
    row = _fetchone(conn, 'SELECT * FROM resume_versions WHERE id = %s AND user_id = %s',
                    (version_id, user_id))
    conn.close()
    return row


def get_latest_resume_version(user_id):
    conn = get_db()
    row = _fetchone(
        conn,
        'SELECT * FROM resume_versions WHERE user_id = %s ORDER BY created_at DESC LIMIT 1',
        (user_id,),
    )
    conn.close()
    return row


def delete_resume_version(version_id, user_id):
    conn = get_db()
    _execute(
        conn,
        'DELETE FROM resume_versions WHERE id = %s AND user_id = %s',
        (version_id, user_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# JD sessions
# ---------------------------------------------------------------------------

def create_jd_session(user_id, jd_text):
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO jd_sessions (user_id, jd_text, created_at) VALUES (%s,%s,%s) RETURNING id',
        (user_id, jd_text, now),
    )
    session_id = cur.fetchone()[0]
    cur.close()
    conn.commit()
    conn.close()
    return session_id


def update_jd_session(session_id, match_score, suggestions):
    conn = get_db()
    _execute(conn, 'UPDATE jd_sessions SET match_score = %s, suggestions_json = %s WHERE id = %s',
             (match_score, json.dumps(suggestions), session_id))
    conn.commit()
    conn.close()


def mark_jd_applied(session_id, version_id):
    conn = get_db()
    _execute(conn, 'UPDATE jd_sessions SET applied_version_id = %s WHERE id = %s',
             (version_id, session_id))
    conn.commit()
    conn.close()


def get_jd_session(session_id, user_id):
    conn = get_db()
    row = _fetchone(conn, 'SELECT * FROM jd_sessions WHERE id = %s AND user_id = %s',
                    (session_id, user_id))
    conn.close()
    if row and isinstance(row.get('suggestions_json'), str):
        row['suggestions'] = json.loads(row['suggestions_json'])
    return row


def list_jd_sessions(user_id):
    conn = get_db()
    rows = _fetchall(
        conn,
        'SELECT id, user_id, match_score, applied_version_id, created_at, '
        'LEFT(jd_text, 200) as jd_preview FROM jd_sessions '
        'WHERE user_id = %s ORDER BY created_at DESC',
        (user_id,),
    )
    conn.close()
    return rows
