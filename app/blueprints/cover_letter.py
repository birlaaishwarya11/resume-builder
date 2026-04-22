"""Cover letter blueprint: editor page, generate, preview, download."""

import io
import traceback
from datetime import datetime

import yaml

from flask import Blueprint, render_template, request, jsonify, send_file
from weasyprint import HTML

from app.blueprints.helpers import (
    login_required, get_current_user_id, get_current_user_settings,
)
from app.models import (
    delete_cover_letter_version,
    get_cover_letter_version,
    list_cover_letter_versions,
    save_cover_letter_version,
)
from app.orchestrator import get_orchestrator

bp = Blueprint('cover_letter', __name__)

_DUMMY_DRAFT = {
    'salutation': 'Dear Hiring Manager,',
    'paragraphs': [
        "I'm excited to apply for the [Role] position at [Company]. With a "
        "background in [your field] and a track record of [one concrete achievement], "
        "I'm confident I can contribute from day one.",
        "At [previous company], I led [project] that delivered [quantified impact]. "
        "That experience taught me [skill] - directly relevant to what [Company] is "
        "building.",
        "I'd welcome the chance to talk about how I can help. Thank you for your "
        "time and consideration.",
    ],
}

_DUMMY_DRAFT_YAML = yaml.dump(
    _DUMMY_DRAFT, default_flow_style=False, allow_unicode=True, sort_keys=False,
)


@bp.route('/cover-letter')
@login_required
def cover_letter_page():
    return render_template('cover_letter_editor.html', draft=_DUMMY_DRAFT_YAML)


def _render_cover_letter_html(yaml_content: str) -> str:
    try:
        draft = yaml.safe_load(yaml_content) or {}
        if not isinstance(draft, dict):
            draft = {}
    except yaml.YAMLError:
        draft = {}

    settings = get_current_user_settings()
    header = settings.get('header') or {}

    return render_template(
        'cover_letter.html',
        date=datetime.now().strftime('%B %d, %Y'),
        salutation=draft.get('salutation', 'Dear Hiring Manager,'),
        paragraphs=draft.get('paragraphs') or [],
        name=header.get('name', ''),
        contact=header.get('contact') or {},
    )


@bp.route('/api/cover_letter/generate', methods=['POST'])
@login_required
def generate():
    user_id = get_current_user_id()
    data = request.json or {}
    jd_text = (data.get('jd_text') or '').strip()
    company = (data.get('company') or '').strip()
    role = (data.get('role') or '').strip()
    hiring_manager = (data.get('hiring_manager') or '').strip()

    if not jd_text or not company:
        return jsonify({'error': 'jd_text and company are required'}), 400

    try:
        orch = get_orchestrator(data, user_id)
        result = orch.generate_cover_letter(
            jd_text, company, role_title=role, hiring_manager=hiring_manager,
        )

        paragraphs = [p.strip() for p in result['text'].split('\n\n') if p.strip()]

        salutation = 'Dear Hiring Manager,'
        if paragraphs and paragraphs[0].lower().startswith('dear'):
            salutation = paragraphs.pop(0)

        body = []
        for p in paragraphs:
            low = p.lower()
            if low.startswith('sincerely') or low.startswith('best regards'):
                break
            body.append(p)

        draft = {'salutation': salutation, 'paragraphs': body}
        yaml_text = yaml.dump(
            draft, default_flow_style=False, allow_unicode=True, sort_keys=False,
        )
        return jsonify({'status': 'success', 'yaml': yaml_text})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        from app.services.ai import extract_ai_error
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


@bp.route('/api/cover_letter/preview', methods=['POST'])
@login_required
def preview():
    data = request.json or {}
    yaml_content = data.get('yaml_content', '')
    html = _render_cover_letter_html(yaml_content)
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@bp.route('/api/cover_letter/download', methods=['POST'])
@login_required
def download():
    src = request.form if request.form else (request.json or {})
    yaml_content = src.get('yaml_content', '')
    keyword = (src.get('keyword') or '').strip()

    html = _render_cover_letter_html(yaml_content)
    pdf_bytes = HTML(string=html).write_pdf()

    if keyword:
        safe = ''.join(c for c in keyword if c.isalnum() or c in ('-', '_'))
        download_name = f'cover_letter_{safe}.pdf' if safe else 'cover_letter.pdf'
    else:
        download_name = 'cover_letter.pdf'

    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name=download_name,
    )


@bp.route('/api/cover_letter/save', methods=['POST'])
@login_required
def save():
    user_id = get_current_user_id()
    data = request.json or {}
    yaml_content = data.get('yaml_content', '')
    keyword = (data.get('keyword') or 'default').strip() or 'default'

    try:
        version_id = save_cover_letter_version(user_id, yaml_content, label=keyword)
        return jsonify({
            'status': 'success',
            'message': f'Saved version {version_id}',
            'version_id': version_id,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/cover_letter/versions', methods=['GET'])
@login_required
def list_versions():
    user_id = get_current_user_id()
    return jsonify(list_cover_letter_versions(user_id))


@bp.route('/api/cover_letter/versions/restore', methods=['POST'])
@login_required
def restore():
    user_id = get_current_user_id()
    data = request.json or {}
    version_id = data.get('version_id')
    if not version_id:
        return jsonify({'error': 'version_id required'}), 400

    row = get_cover_letter_version(version_id, user_id)
    if not row:
        return jsonify({'error': 'version not found'}), 404
    return jsonify({'status': 'ok', 'yaml': row['yaml_content']})


@bp.route('/api/cover_letter/versions/<int:version_id>', methods=['DELETE'])
@login_required
def delete_version(version_id):
    user_id = get_current_user_id()
    if not get_cover_letter_version(version_id, user_id):
        return jsonify({'error': 'version not found'}), 404
    delete_cover_letter_version(version_id, user_id)
    return jsonify({'status': 'ok'})


