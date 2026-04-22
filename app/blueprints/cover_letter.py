"""Cover letter blueprint: editor page, generate, preview, download."""

import io
import os
import traceback
import yaml

from flask import Blueprint, render_template, request, jsonify, send_file
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.blueprints.helpers import login_required, get_current_user_id, md_bold
from app.models import get_user_settings
from app.orchestrator import get_orchestrator
from app.services import documents

bp = Blueprint('cover_letter', __name__)

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'templates',
)


def _load_draft(user_id):
    raw = documents.get_cover_letter_draft(user_id)
    if not raw:
        return {}
    try:
        return yaml.safe_load(raw) or {}
    except Exception:
        return {}


def _save_draft(user_id, draft):
    yaml_text = yaml.dump(
        draft, default_flow_style=False, allow_unicode=True, sort_keys=False,
    )
    documents.save_cover_letter_draft(user_id, yaml_text)


@bp.route('/cover-letter')
@login_required
def cover_letter_page():
    user_id = get_current_user_id()
    draft = _load_draft(user_id)
    settings = get_user_settings(user_id)
    return render_template('cover_letter_editor.html',
                           draft=draft, settings=settings)


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
            jd_text, company, role_title=role, hiring_manager=hiring_manager
        )

        text = result['text']
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        salutation = 'Dear Hiring Manager,'
        if paragraphs and paragraphs[0].lower().startswith('dear'):
            salutation = paragraphs.pop(0)

        body_paragraphs = []
        for p in paragraphs:
            if p.lower().startswith('sincerely') or p.lower().startswith('best regards'):
                break
            body_paragraphs.append(p)

        draft = {
            'salutation': salutation,
            'paragraphs': body_paragraphs,
        }

        _save_draft(user_id, draft)

        return jsonify({
            'status': 'success',
            'draft': draft,
            'stories_used': result.get('stories_used', []),
        })
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
    user_id = get_current_user_id()
    data = request.json or {}
    draft = data.get('draft', {})

    settings = get_user_settings(user_id)
    header = settings.get('header', {})
    style = settings.get('style', {})

    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))
    env.filters['md_bold'] = md_bold
    template = env.get_template('cover_letter.html')
    html = template.render(
        draft=draft, header=header, style=style,
    )
    return jsonify({'html': html})


@bp.route('/api/cover_letter/download', methods=['POST'])
@login_required
def download():
    user_id = get_current_user_id()
    data = request.json or {}
    draft = data.get('draft', {})

    settings = get_user_settings(user_id)
    header = settings.get('header', {})
    style = settings.get('style', {})

    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))
    env.filters['md_bold'] = md_bold
    template = env.get_template('cover_letter.html')
    html = template.render(draft=draft, header=header, style=style)

    pdf_bytes = HTML(string=html).write_pdf()
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name='cover_letter.pdf',
    )


@bp.route('/api/cover_letter/draft', methods=['GET', 'PUT'])
@login_required
def draft():
    user_id = get_current_user_id()

    if request.method == 'GET':
        return jsonify(_load_draft(user_id))

    data = request.json or {}
    _save_draft(user_id, data)
    return jsonify({'status': 'ok'})
