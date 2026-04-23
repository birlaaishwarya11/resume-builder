"""Databases blueprint: full-page editors for candidate DB, resume rules, CL DB, CL rules."""

import traceback

from flask import Blueprint, render_template, request, jsonify

from app.agents.database_builder import validate_rules_content
from app.blueprints.helpers import login_required, get_current_user_id
from app.models import get_document, save_document
from app.orchestrator import resolve_ai_credentials
from app.services.ai import extract_ai_error

bp = Blueprint('databases', __name__)

# Hard cap on a single document. Bounds prompt size and per-call cost when this
# content is fed into agent prompts; also blocks paste-bomb DoS on storage.
MAX_DOCUMENT_BYTES = 64 * 1024  # 64 KB

# Map URL-facing type names to the document field in user_documents.
_DB_FIELDS = {
    'candidate': 'candidate_database',
    'resume_rules': 'resume_rules',
    'cover_letter': 'cover_letter_database',
    'cover_letter_rules': 'cover_letter_rules',
}

_DB_TITLES = {
    'candidate': 'Candidate Database',
    'resume_rules': 'Resume Rules',
    'cover_letter': 'Cover Letter Database',
    'cover_letter_rules': 'Cover Letter Rules',
}


# --- Full-page editor routes ---

@bp.route('/databases/candidate')
@login_required
def candidate_page():
    return render_template('databases/candidate.html',
                           db_type='candidate', title='Candidate Database')


@bp.route('/databases/resume-rules')
@login_required
def resume_rules_page():
    return render_template('databases/resume_rules.html',
                           db_type='resume_rules', title='Resume Rules')


@bp.route('/databases/cover-letter')
@login_required
def cover_letter_db_page():
    return render_template('databases/cover_letter_db.html',
                           db_type='cover_letter', title='Cover Letter Database')


@bp.route('/databases/cover-letter-rules')
@login_required
def cover_letter_rules_page():
    return render_template('databases/cover_letter_rules.html',
                           db_type='cover_letter_rules', title='Cover Letter Rules')


# --- API routes (GET/PUT for each) ---

@bp.route('/api/databases/<db_type>', methods=['GET', 'PUT'])
@login_required
def api_database(db_type):
    user_id = get_current_user_id()
    field = _DB_FIELDS.get(db_type)
    if not field:
        return jsonify({'error': f'Unknown database type: {db_type}'}), 400

    if request.method == 'GET':
        content = get_document(user_id, field)
        return jsonify({'content': content, 'type': db_type,
                        'title': _DB_TITLES.get(db_type, db_type)})

    data = request.json or {}
    content = data.get('content', '') or ''
    if not isinstance(content, str):
        return jsonify({'error': 'content must be a string'}), 400
    if len(content.encode('utf-8')) > MAX_DOCUMENT_BYTES:
        return jsonify({
            'error': f'Document exceeds {MAX_DOCUMENT_BYTES // 1024} KB limit',
        }), 413
    save_document(user_id, field, content)
    return jsonify({'status': 'ok'})


# --- Topic-relevance validator (rules only) ---

_VALIDATABLE_TYPES = ('resume_rules', 'cover_letter_rules')


@bp.route('/api/databases/<db_type>/validate', methods=['POST'])
@login_required
def validate_database(db_type):
    """Run an LLM topic-relevance check on rules content before save.

    Body: ``{content: str, provider?, api_key?, model?}``. Returns the
    validator JSON ``{relevant, issues[], summary}``. Always non-blocking
    -- the caller decides whether to honour the verdict. If the user has
    no API key, the endpoint returns 400 and the UI can fall back to
    saving without validation.
    """
    user_id = get_current_user_id()
    if db_type not in _VALIDATABLE_TYPES:
        return jsonify({
            'error': f'Validation not supported for {db_type!r}',
        }), 400
    data = request.json or {}
    content = data.get('content', '')
    if not isinstance(content, str):
        return jsonify({'error': 'content must be a string'}), 400
    if len(content.encode('utf-8')) > MAX_DOCUMENT_BYTES:
        return jsonify({
            'error': f'content exceeds {MAX_DOCUMENT_BYTES // 1024} KB limit',
        }), 413

    try:
        provider, api_key, model = resolve_ai_credentials(data, user_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        result = validate_rules_content(db_type, content, provider, api_key, model)
        return jsonify({'status': 'success', **result})
    except Exception as e:
        traceback.print_exc()
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


# Backward-compatible settings API aliases
@bp.route('/api/settings/candidate_database', methods=['GET', 'PUT'])
@login_required
def settings_candidate_database():
    return api_database('candidate')


@bp.route('/api/settings/resume_rules', methods=['GET', 'PUT'])
@login_required
def settings_resume_rules():
    return api_database('resume_rules')


@bp.route('/api/settings/cover_letter_database', methods=['GET', 'PUT'])
@login_required
def settings_cover_letter_database():
    return api_database('cover_letter')


@bp.route('/api/settings/cover_letter_rules', methods=['GET', 'PUT'])
@login_required
def settings_cover_letter_rules():
    return api_database('cover_letter_rules')
