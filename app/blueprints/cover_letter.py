"""Cover letter blueprint: editor page, generate, preview, download."""

import os
import traceback
import yaml

from flask import Blueprint, render_template, request, jsonify, send_file
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.blueprints.helpers import login_required, get_current_user_id, md_bold
from app.models import get_user_dir, get_user_settings
from app.orchestrator import get_orchestrator

bp = Blueprint('cover_letter', __name__)

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'templates',
)


@bp.route('/cover-letter')
@login_required
def cover_letter_page():
    user_id = get_current_user_id()
    draft_path = os.path.join(get_user_dir(user_id), 'cover_letter_draft.yaml')
    draft = {}
    if os.path.exists(draft_path):
        with open(draft_path, 'r', encoding='utf-8') as f:
            draft = yaml.safe_load(f) or {}
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

        # Parse into structured YAML for the editor
        text = result['text']
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        salutation = 'Dear Hiring Manager,'
        if paragraphs and paragraphs[0].lower().startswith('dear'):
            salutation = paragraphs.pop(0)

        # Remove signature block if present
        body_paragraphs = []
        for p in paragraphs:
            if p.lower().startswith('sincerely') or p.lower().startswith('best regards'):
                break
            body_paragraphs.append(p)

        draft = {
            'salutation': salutation,
            'paragraphs': body_paragraphs,
        }

        # Save draft YAML
        draft_path = os.path.join(get_user_dir(user_id), 'cover_letter_draft.yaml')
        with open(draft_path, 'w', encoding='utf-8') as f:
            yaml.dump(draft, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

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

    user_dir = get_user_dir(user_id)
    os.makedirs(user_dir, exist_ok=True)
    pdf_path = os.path.join(user_dir, 'cover_letter.pdf')
    HTML(string=html).write_pdf(pdf_path)

    return send_file(pdf_path, mimetype='application/pdf',
                     as_attachment=True, download_name='cover_letter.pdf')


@bp.route('/api/cover_letter/draft', methods=['GET', 'PUT'])
@login_required
def draft():
    user_id = get_current_user_id()
    draft_path = os.path.join(get_user_dir(user_id), 'cover_letter_draft.yaml')

    if request.method == 'GET':
        if os.path.exists(draft_path):
            with open(draft_path, 'r', encoding='utf-8') as f:
                content = yaml.safe_load(f) or {}
            return jsonify(content)
        return jsonify({})

    data = request.json or {}
    os.makedirs(os.path.dirname(draft_path), exist_ok=True)
    with open(draft_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return jsonify({'status': 'ok'})
