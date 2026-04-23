"""Settings blueprint: full-page settings, AI config CRUD."""

from flask import Blueprint, render_template, request, jsonify

from app.blueprints.helpers import (
    login_required, get_current_user_id, invalidate_current_user_settings,
)
from app.models import (
    get_user_settings, update_user_settings,
    save_user_api_config, get_user_api_config, delete_user_api_config,
    get_user_by_id, verify_user_password, delete_user,
    generate_mcp_api_key, get_mcp_api_key,
)
from app.services.crypto import encrypt_api_key, decrypt_api_key
from app.services import documents

bp = Blueprint('settings', __name__)


@bp.route('/settings')
@login_required
def settings_page():
    user_id = get_current_user_id()
    user = get_user_by_id(user_id)
    settings = get_user_settings(user_id)
    return render_template('settings.html', user=user, settings=settings)


@bp.route('/knowledge')
@login_required
def knowledge_page():
    user_id = get_current_user_id()
    user = get_user_by_id(user_id)

    def _kb(text: str) -> int:
        if not text:
            return 0
        return len(text.encode('utf-8'))

    sizes = {
        'candidate': _kb(documents.get_candidate_database(user_id)),
        'cover_letter': _kb(documents.get_cover_letter_database(user_id)),
        'resume_rules': _kb(documents.get_resume_rules(user_id)),
        'cover_letter_rules': _kb(documents.get_cover_letter_rules(user_id)),
    }
    return render_template('knowledge.html', user=user, sizes=sizes)


@bp.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    user_id = get_current_user_id()

    if request.method == 'GET':
        settings = get_user_settings(user_id)
        return jsonify(settings)

    data = request.json or {}
    update_user_settings(
        user_id,
        header=data.get('header'),
        section_names=data.get('section_names'),
        custom_sections=data.get('custom_sections'),
        style=data.get('style'),
    )
    invalidate_current_user_settings()
    return jsonify({'status': 'ok'})


@bp.route('/api/settings/ai_config', methods=['GET', 'POST', 'DELETE'])
@login_required
def ai_config():
    user_id = get_current_user_id()

    if request.method == 'GET':
        config = get_user_api_config(user_id)
        if config:
            return jsonify({
                'provider': config.get('provider', ''),
                'has_key': True,
                'model': config.get('model', ''),
            })
        return jsonify({'provider': '', 'has_key': False, 'model': ''})

    if request.method == 'DELETE':
        delete_user_api_config(user_id)
        return jsonify({'status': 'ok'})

    data = request.json or {}
    provider = data.get('provider', 'anthropic')
    api_key = data.get('api_key', '').strip()
    model = data.get('model', '').strip() or None

    if not api_key:
        return jsonify({'error': 'API key is required'}), 400

    encrypted = encrypt_api_key(api_key)
    save_user_api_config(user_id, provider, encrypted, model)
    return jsonify({'status': 'ok'})


@bp.route('/api/mcp_key', methods=['GET', 'POST'])
@login_required
def mcp_key():
    user_id = get_current_user_id()
    if request.method == 'GET':
        key = get_mcp_api_key(user_id)
        return jsonify({'key': key})
    key = generate_mcp_api_key(user_id)
    return jsonify({'key': key})


@bp.route('/api/mcp_key/regenerate', methods=['POST'])
@login_required
def mcp_key_regenerate():
    user_id = get_current_user_id()
    key = generate_mcp_api_key(user_id)
    return jsonify({'key': key})


@bp.route('/api/delete_profile', methods=['POST'])
@login_required
def delete_profile():
    user_id = get_current_user_id()
    data = request.json or {}
    password = data.get('password', '')
    if not verify_user_password(user_id, password):
        return jsonify({'error': 'Incorrect password'}), 403
    delete_user(user_id)
    from flask import session as flask_session
    flask_session.clear()
    return jsonify({'status': 'ok'})
