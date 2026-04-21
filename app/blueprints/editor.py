"""Editor blueprint: main resume editor page and its API endpoints."""

import glob
import io
import json
import logging
import os
from datetime import datetime

import yaml
from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.blueprints.helpers import (
    BUILTIN_KEYS,
    get_current_custom_sections,
    get_current_section_names,
    get_current_user_header,
    get_current_user_id,
    infer_render_type,
    load_yaml,
    login_required,
    md_bold,
    merge_header,
    strip_header,
)
from app.models import (
    DATA_DIR,
    DEFAULT_SECTION_NAMES,
    get_user_by_id,
    get_user_dir,
    get_user_settings,
    get_user_versions_dir,
    is_onboarding_complete,
)
from app.services.resume import (
    dump_yaml,
    get_current_resume,
    parse_yaml,
    save_current_resume,
)

logger = logging.getLogger(__name__)

bp = Blueprint('editor', __name__)

# Template directory lives at the project root, two levels above this file.
_BLUEPRINT_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_BLUEPRINT_DIR)
BASE_DIR = os.path.dirname(_APP_DIR)
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')


# ---------------------------------------------------------------------------
# Rendering helpers (shared by preview + download)
# ---------------------------------------------------------------------------

def _render_resume_html(resume_yaml, style, header=None, section_names=None,
                        custom_sections=None):
    """Parse YAML, merge header, and render resume.html to an HTML string."""
    header = header or get_current_user_header()
    section_names = section_names or get_current_section_names()
    custom_sections = custom_sections or get_current_custom_sections()

    resume_data = merge_header(resume_yaml, header)

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    env.filters['md_bold'] = md_bold
    template = env.get_template('resume.html')
    return template.render(
        resume=resume_data,
        style=style,
        section_names=section_names,
        custom_sections=custom_sections,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/')
@login_required
def index():
    """Main editor page -- renders editor.html with the current resume."""
    user_id = get_current_user_id()
    if not is_onboarding_complete(user_id):
        return redirect(url_for('onboarding.onboarding_page'))

    user_dir = get_user_dir(user_id)
    header = get_current_user_header()
    section_names = get_current_section_names()
    custom_sections = get_current_custom_sections()
    user = get_user_by_id(user_id)

    resume_path = os.path.join(user_dir, 'resume.yaml')
    has_resume = os.path.exists(resume_path)

    if has_resume:
        resume_data = load_yaml(resume_path)
        editable_data = strip_header(resume_data, header)
    else:
        editable_data = {}

    # Load saved style from user settings, with defaults.
    settings = get_user_settings(user_id)
    saved_style = settings.get('style', {})
    style = {
        'font_family': saved_style.get('font_family', '"Times New Roman", Times, serif'),
        'font_size': saved_style.get('font_size', '10pt'),
        'line_height': saved_style.get('line_height', '1.2'),
        'margin': saved_style.get('margin', '0.4in'),
        'accent_color': saved_style.get('accent_color', '#000000'),
    }

    resume_yaml = dump_yaml(editable_data) if editable_data else ''

    return render_template(
        'editor.html',
        resume=resume_yaml,
        style=style,
        fixed_header=header,
        section_names=section_names,
        custom_sections=custom_sections,
        user=user,
        has_resume=has_resume,
    )


@bp.route('/api/preview', methods=['POST'])
@login_required
def preview():
    """Render YAML + style to HTML (uses resume.html with md_bold filter)."""
    data = request.json
    resume_yaml = data.get('resume', '')
    style = data.get('style', {})

    try:
        # Allow overrides from the request (used during onboarding before
        # settings are persisted).
        header = data.get('header') or get_current_user_header()
        section_names = data.get('section_names') or get_current_section_names()
        custom_sections = data.get('custom_sections') or get_current_custom_sections()

        html_content = _render_resume_html(
            resume_yaml, style,
            header=header,
            section_names=section_names,
            custom_sections=custom_sections,
        )
        return html_content
    except Exception as e:
        return str(e), 400


@bp.route('/api/save', methods=['POST'])
@login_required
def save():
    """Save the current YAML as a new version (DB + legacy file)."""
    data = request.json
    resume_yaml = data.get('resume', '')
    keyword = data.get('keyword', 'default')

    # Optional tags for JD matching, e.g. ["python", "backend", "aws"].
    tags = data.get('tags') or None
    if isinstance(tags, list):
        tags = [str(t).strip() for t in tags if str(t).strip()]
    if not tags:
        tags = None

    try:
        user_id = get_current_user_id()
        versions_dir = get_user_versions_dir(user_id)
        header = get_current_user_header()
        user = get_user_by_id(user_id)

        full_data = merge_header(resume_yaml, header)
        full_yaml = yaml.dump(full_data, sort_keys=False, allow_unicode=True)

        # Save main file + DB version row (with optional tags).
        version_id = save_current_resume(
            user_id, full_yaml, source='manual_edit', label=keyword, tags=tags,
        )

        # Also write a legacy file-based version for backward compatibility.
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_keyword = ''.join(
            c for c in keyword if c.isalnum() or c in ('-', '_')
        ).strip() or 'default'
        safe_name = ''.join(
            c for c in user['name'] if c.isalnum() or c in (' ', '-', '_')
        ).strip().replace(' ', '_')
        version_filename = f'{safe_name}_{safe_keyword}_{timestamp}.yaml'

        os.makedirs(versions_dir, exist_ok=True)
        with open(os.path.join(versions_dir, version_filename), 'w') as f:
            f.write(full_yaml)

        return jsonify({
            'status': 'success',
            'message': f'Saved as {version_filename}',
            'version_id': version_id,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/download_pdf', methods=['POST'])
@login_required
def download_pdf():
    """Render the resume to PDF via WeasyPrint and return as a file download."""
    data = request.json
    resume_yaml = data.get('resume', '')
    style = data.get('style', {})
    keyword = data.get('keyword', '')
    inline = data.get('inline', False)

    try:
        user_id = get_current_user_id()
        user_dir = get_user_dir(user_id)
        user = get_user_by_id(user_id)

        html_content = _render_resume_html(resume_yaml, style)

        pdf_path = os.path.join(user_dir, 'preview.pdf')
        HTML(string=html_content, base_url=BASE_DIR).write_pdf(pdf_path)

        safe_name = ''.join(
            c for c in user['name'] if c.isalnum() or c in (' ', '-', '_')
        ).strip().replace(' ', '_')

        if keyword:
            safe_keyword = ''.join(
                c for c in keyword if c.isalnum() or c in ('-', '_')
            ).strip()
            download_name = f'{safe_name}_{safe_keyword}.pdf'
        else:
            download_name = f'{safe_name}_Resume.pdf'

        return send_file(pdf_path, as_attachment=not inline,
                         download_name=download_name)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/history')
@login_required
def history():
    """List file-based version history (legacy glob-based)."""
    user_id = get_current_user_id()
    versions_dir = get_user_versions_dir(user_id)

    if not os.path.exists(versions_dir):
        return jsonify([])

    files = glob.glob(os.path.join(versions_dir, '*.yaml'))
    files.sort(key=os.path.getmtime, reverse=True)

    history_list = []
    for f in files:
        filename = os.path.basename(f)
        timestamp = datetime.fromtimestamp(
            os.path.getmtime(f)
        ).strftime('%Y-%m-%d %H:%M:%S')
        history_list.append({'filename': filename, 'timestamp': timestamp})

    return jsonify(history_list)


@bp.route('/api/load/<filename>')
@login_required
def load_version(filename):
    """Load YAML content from a versioned file."""
    try:
        user_id = get_current_user_id()
        versions_dir = get_user_versions_dir(user_id)
        header = get_current_user_header()

        # Sanitize filename to prevent directory traversal.
        filename = os.path.basename(filename)
        filepath = os.path.join(versions_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({'status': 'error', 'message': 'File not found'}), 404

        with open(filepath, 'r') as f:
            content = f.read()

        editable_data = strip_header(content, header)
        editable_yaml = dump_yaml(editable_data)

        return jsonify({'status': 'success', 'content': editable_yaml})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/delete_version/<filename>', methods=['DELETE'])
@login_required
def delete_version(filename):
    """Delete a file-based version."""
    try:
        user_id = get_current_user_id()
        versions_dir = get_user_versions_dir(user_id)

        # Sanitize filename to prevent directory traversal.
        filename = os.path.basename(filename)
        filepath = os.path.join(versions_dir, filename)

        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'status': 'success', 'message': f'Deleted {filename}'})
        else:
            return jsonify({'status': 'error', 'message': 'File not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/feedback', methods=['POST'])
@login_required
def submit_feedback():
    """Save user feedback to feedback.jsonl."""
    data = request.json
    feedback_text = data.get('feedback', '').strip()

    if not feedback_text:
        return jsonify({'status': 'error', 'message': 'Feedback cannot be empty.'}), 400

    user_id = get_current_user_id()
    user = get_user_by_id(user_id)
    user_name = user['name'] if user else 'Unknown'

    feedback_file = os.path.join(DATA_DIR, 'feedback.jsonl')
    entry = {
        'timestamp': datetime.now().isoformat(),
        'user_name': user_name,
        'user_id': user_id,
        'feedback': feedback_text,
    }

    try:
        with open(feedback_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return jsonify({'status': 'success', 'message': 'Thank you for your feedback!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/check_grammar', methods=['POST'])
@login_required
def check_grammar():
    """Grammar check via language_tool_python (local) or public LanguageTool API."""
    user_id = get_current_user_id()
    data = request.json
    resume_yaml = data.get('resume', '')
    provider = data.get('provider', 'anthropic')
    model = data.get('model', '')

    if not resume_yaml:
        return jsonify({'status': 'error', 'message': 'Missing resume content'}), 400

    # ------------------------------------------------------------------
    # Offline / local mode
    # ------------------------------------------------------------------
    if provider == 'local':
        try:
            clean_text = _extract_text_from_yaml(resume_yaml)

            import language_tool_python  # noqa: delay import

            try:
                tool = language_tool_python.LanguageTool('en-US')
                matches = tool.check(clean_text)

                results = _build_grammar_results_local(matches, clean_text)
                return jsonify({'status': 'success', 'results': results})

            except Exception as local_err:
                logger.warning('Local Java server failed: %s. Falling back to public API.', local_err)
                import requests
                response = requests.post(
                    'https://api.languagetool.org/v2/check',
                    data={'text': clean_text, 'language': 'en-US'},
                )
                if response.status_code != 200:
                    raise RuntimeError(f'Public API error: {response.text}')

                api_data = response.json()
                results = _build_grammar_results_api(api_data.get('matches', []), clean_text)
                return jsonify({'status': 'success', 'results': results})

        except ImportError:
            return jsonify({
                'status': 'error',
                'message': 'language-tool-python or requests not installed',
            }), 500
        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': f'Grammar check failed: {str(e)}',
            }), 500

    # ------------------------------------------------------------------
    # AI mode
    # ------------------------------------------------------------------
    from app.orchestrator import resolve_ai_credentials
    from app.services.ai import call_llm, parse_json_response

    try:
        ai_provider, api_key, ai_model = resolve_ai_credentials(data, user_id)
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

    try:
        system_prompt = (
            'You are a professional resume editor. Proofread the following resume '
            'YAML content for spelling and grammar errors. Focus on the content '
            'values, ignoring keys and structure.\n'
            'Return a JSON list of objects. Each object must have:\n'
            '- "original": string\n'
            '- "correction": string\n'
            '- "explanation": string\n'
            '- "location": string\n'
            'If no errors are found, return an empty list.'
        )
        user_msg = f'RESUME CONTENT:\n{resume_yaml}'
        response_text = call_llm(ai_provider, api_key, system_prompt, user_msg, ai_model)
        results = parse_json_response(response_text)
        return jsonify({'status': 'success', 'results': results})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# Grammar-check helpers
# ---------------------------------------------------------------------------

def _extract_text_from_yaml(resume_yaml: str) -> str:
    """Recursively pull all string values from parsed YAML."""
    def _get_text_values(data):
        values = []
        if isinstance(data, dict):
            for v in data.values():
                values.extend(_get_text_values(v))
        elif isinstance(data, list):
            for item in data:
                values.extend(_get_text_values(item))
        elif isinstance(data, str):
            values.append(data)
        return values

    try:
        parsed = yaml.safe_load(resume_yaml)
        segments = _get_text_values(parsed)
        return '\n\n'.join(segments)
    except Exception:
        return resume_yaml


def _build_grammar_results_local(matches, clean_text: str) -> list[dict]:
    """Convert language_tool_python matches to our JSON format."""
    results = []
    for match in matches:
        context = match.context
        if '{{' in context or '{%' in context:
            continue
        results.append({
            'original': clean_text[match.offset: match.offset + match.errorLength],
            'correction': match.replacements[0] if match.replacements else '',
            'explanation': match.message,
            'location': 'Content Match',
        })
    return results


def _build_grammar_results_api(matches: list, clean_text: str) -> list[dict]:
    """Convert public LanguageTool API matches to our JSON format."""
    results = []
    for match in matches:
        offset = match['offset']
        length = match['length']
        context_text = match.get('context', {}).get('text', '')
        if '{{' in context_text or '{%' in context_text:
            continue
        replacements = match.get('replacements', [])
        correction = replacements[0]['value'] if replacements else ''
        results.append({
            'original': clean_text[offset: offset + length],
            'correction': correction,
            'explanation': match['message'],
            'location': 'Content Match',
        })
    return results
