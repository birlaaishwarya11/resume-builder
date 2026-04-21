"""Databases blueprint: full-page editors for candidate DB, resume rules, CL DB, CL rules."""

import os
from flask import Blueprint, render_template, request, jsonify

from app.blueprints.helpers import login_required, get_current_user_id
from app.models import get_user_dir

bp = Blueprint('databases', __name__)

_DB_FILES = {
    'candidate': 'candidate_database.md',
    'resume_rules': 'resume_rules.md',
    'cover_letter': 'cover_letter_database.md',
    'cover_letter_rules': 'cover_letter_rules.md',
}

_DB_TITLES = {
    'candidate': 'Candidate Database',
    'resume_rules': 'Resume Rules',
    'cover_letter': 'Cover Letter Database',
    'cover_letter_rules': 'Cover Letter Rules',
}


def _get_db_path(user_id, db_type):
    filename = _DB_FILES.get(db_type)
    if not filename:
        return None
    return os.path.join(get_user_dir(user_id), filename)


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
    path = _get_db_path(user_id, db_type)
    if not path:
        return jsonify({'error': f'Unknown database type: {db_type}'}), 400

    if request.method == 'GET':
        content = ''
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        return jsonify({'content': content, 'type': db_type,
                        'title': _DB_TITLES.get(db_type, db_type)})

    data = request.json or {}
    content = data.get('content', '')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({'status': 'ok'})


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
