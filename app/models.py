"""Database models and queries -- PostgreSQL only.

All queries use psycopg2 with %s placeholders. No SQLite support.
"""

import json
import os
import shutil
import secrets
from datetime import datetime

import psycopg2
import psycopg2.extras
import psycopg2.errors
from werkzeug.security import generate_password_hash, check_password_hash

from app.config import Config

DATABASE_URL = Config.DATABASE_URL
DATA_DIR = Config.DATA_DIR

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _copy_default_user_files(user_dir: str):
    """Copy default template files into a new user's data directory."""
    defaults_dir = os.path.join(DATA_DIR, 'defaults')
    for filename in ('candidate_database.md', 'resume_rules.md',
                     'cover_letter_database.md', 'cover_letter_rules.md'):
        dest = os.path.join(user_dir, filename)
        if not os.path.exists(dest):
            src = os.path.join(defaults_dir, filename)
            if os.path.exists(src):
                shutil.copy2(src, dest)
            else:
                title = filename.replace('_', ' ').replace('.md', '').title()
                with open(dest, 'w', encoding='utf-8') as f:
                    f.write(f"# {title}\n\nAdd your content here.\n")


def get_db():
    """Return a new PostgreSQL connection."""
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def _fetchone(conn, query, params=()):
    """Execute a query and return one row as a dict, or None."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def _fetchall(conn, query, params=()):
    """Execute a query and return all rows as a list of dicts."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def _execute(conn, query, params=()):
    """Execute a query (INSERT/UPDATE/DELETE)."""
    cur = conn.cursor()
    cur.execute(query, params)
    cur.close()


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

def init_db():
    """Create tables and run migrations."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_db()
    cur = conn.cursor()

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

    # Migrations for existing databases -- safe to run repeatedly
    _safe_add_column(cur, 'users', 'mcp_api_key', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'user_settings', 'ai_provider', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'user_settings', 'ai_api_key_encrypted', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'user_settings', 'ai_model', 'TEXT DEFAULT NULL')
    _safe_add_column(cur, 'resume_versions', 'tags', 'TEXT DEFAULT NULL')

    # Reset verbose legacy section name defaults to simple ones
    cur.execute(
        "UPDATE user_settings SET section_names_json = %s WHERE section_names_json = %s",
        (json.dumps(DEFAULT_SECTION_NAMES), _OLD_SECTION_NAMES_JSON),
    )
    conn.commit()
    cur.close()
    conn.close()


def _safe_add_column(cur, table, column, definition):
    """Add a column if it doesn't already exist (PostgreSQL)."""
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
        conn.commit()

        user_dir = os.path.join(DATA_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)
        os.makedirs(os.path.join(user_dir, 'versions'), exist_ok=True)
        _copy_default_user_files(user_dir)

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
    """Return user dict if credentials match, else None."""
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


def get_user_dir(user_id):
    return os.path.join(DATA_DIR, str(user_id))


def get_user_versions_dir(user_id):
    return os.path.join(DATA_DIR, str(user_id), 'versions')


def delete_user(user_id):
    """Delete a user account, settings, and all workspace data."""
    conn = get_db()
    _execute(conn, 'DELETE FROM users WHERE id = %s', (user_id,))
    conn.commit()
    conn.close()
    user_dir = get_user_dir(user_id)
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)


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
    """Save the user's AI provider configuration."""
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
    """Return the user's AI config dict, or None if not configured."""
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
    """Return best parser: LOCKED first, then ACTIVE, or None."""
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

RESUME_SOURCES = ('upload', 'manual_edit', 'jd_applied', 'ai_edit')


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
