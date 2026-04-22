"""Onboarding blueprint: PDF upload, parsing, review, and completion."""

import logging
import os
import tempfile

import yaml
from flask import (
    Blueprint, render_template, request, jsonify,
    redirect, send_file, url_for,
)

from app.blueprints.helpers import (
    login_required, get_current_user_id, get_current_user_header,
    strip_header, merge_header, md_bold,
    BUILTIN_KEYS, infer_render_type, has_meaningful_content,
    clean_parsed_resume, build_raw_text,
)
from app.models import (
    get_user_settings, is_onboarding_complete,
    mark_onboarding_complete, update_user_settings,
    DEFAULT_SECTION_NAMES, get_user_by_id,
    get_user_api_config,
)
from app.services.resume import save_current_resume, parse_yaml, dump_yaml
from app.services.ai import call_llm, extract_ai_error
from app.services.crypto import decrypt_api_key
from app.parsers.pdf import (
    extract_text_local, extract_style_from_pdf,
    parse_resume_from_extracted, _smart_parse_section, _normalize_section_key,
)
from app.parsers.confidence import score_parsed_resume
from app.parsers.smart import normalize_dates, resolve_parser_credentials
import app.services.parser as parser_service

logger = logging.getLogger(__name__)

bp = Blueprint('onboarding', __name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _onboarding_pdf_path(user_id: int) -> str:
    """Return a per-user tmp path for the uploaded PDF (onboarding only)."""
    return os.path.join(tempfile.gettempdir(), f'resume_builder_onboarding_{user_id}.pdf')


def _resolve_ai_credentials(request_data: dict, user_id: int) -> tuple:
    """Return (provider, api_key, model) from request body or DB.

    Request body values override DB-stored config.  Raises ``ValueError``
    if no API key is available from either source.
    """
    provider = (
        request_data.get('provider')
        or request_data.get('ai_provider')
        or ''
    ).strip()
    api_key = (
        request_data.get('api_key')
        or request_data.get('ai_api_key')
        or ''
    ).strip()
    model = (
        request_data.get('model')
        or request_data.get('ai_model')
        or ''
    ).strip() or None

    if not api_key:
        config = get_user_api_config(user_id)
        if config and config.get('ai_api_key_encrypted'):
            api_key = decrypt_api_key(config['ai_api_key_encrypted'])
            provider = provider or config.get('provider') or 'anthropic'
            model = model or config.get('model')

    if not api_key:
        raise ValueError(
            "No API key configured. Set one in Settings or pass it in the request."
        )

    return provider or 'anthropic', api_key, model


def _search_section_local(pdf_path: str, section_hint: str) -> dict:
    """Local fallback for section search using pdfplumber."""
    try:
        extracted = extract_text_local(pdf_path)
        if not extracted or not extracted.get('pages'):
            return {"found": False}

        hint_lower = section_hint.lower().strip()

        all_lines = []
        for page in extracted['pages']:
            for line in page.get('lines', []):
                all_lines.append(line)

        for i, line in enumerate(all_lines):
            line_lower = line.get('text', '').lower().strip()
            if hint_lower in line_lower or line_lower in hint_lower:
                alpha = [c for c in line.get('text', '') if c.isalpha()]
                is_caps = (
                    alpha
                    and all(c.isupper() for c in alpha)
                    and len(alpha) > 2
                )
                if line.get('bold') or is_caps or line.get('size', 10) > 11:
                    context_lines = all_lines[i + 1 : i + 31]
                    return {
                        "found": True,
                        "heading": line['text'],
                        "lines": context_lines,
                    }

        return {"found": False}
    except Exception:
        return {"found": False}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/onboarding')
@login_required
def onboarding_page():
    """Render the onboarding page, or redirect to editor if already done."""
    user_id = get_current_user_id()
    if is_onboarding_complete(user_id):
        return redirect(url_for('editor.index'))
    user = get_user_by_id(user_id)
    return render_template('onboarding.html', user=user)


@bp.route('/api/upload_resume', methods=['POST'])
@login_required
def upload_resume():
    """Upload and parse a PDF during onboarding.

    Pipeline (in priority order):
      1. Extract text locally
      2. Parse:
         a. Locked smart parser (stored code)
         b. Active smart parser
         c. Generate new smart parser (if credentials available)
         d. Heuristic fallback -- always works, no key required
      3. Return YAML + header + confidence + style
    """
    user_id = get_current_user_id()
    if is_onboarding_complete(user_id):
        return jsonify({"status": "error", "message": "Onboarding already completed."}), 400

    pdf_file = request.files.get('resume_pdf')
    if not pdf_file or not pdf_file.filename or not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({"status": "error", "message": "Please upload a valid PDF file."}), 400

    form_data = {
        'ai_provider': request.form.get('ai_provider', ''),
        'ai_api_key': request.form.get('ai_api_key', ''),
        'ai_model': request.form.get('ai_model', ''),
    }
    try:
        ai_provider, ai_api_key, ai_model = _resolve_ai_credentials(form_data, user_id)
    except ValueError:
        ai_provider, ai_api_key, ai_model = '', '', ''

    pdf_path = _onboarding_pdf_path(user_id)
    pdf_file.save(pdf_path)

    try:
        extracted_style = extract_style_from_pdf(pdf_path)

        extracted_data = extract_text_local(pdf_path)
        extraction_source = 'local'

        if not extracted_data or not extracted_data.get('pages'):
            return jsonify({
                "status": "error",
                "message": "Could not extract text from PDF. The file may be image-only or corrupted.",
            }), 500

        flat_lines = []
        for page in extracted_data.get('pages', []):
            flat_lines.extend(page.get('lines', []))

        raw_text = build_raw_text(extracted_data)

        sp_provider, sp_api_key, sp_model = resolve_parser_credentials(
            ai_provider, ai_api_key, ai_model,
        )

        parsed = None
        ai_error_info = None
        parser_used = 'heuristic'
        generated_parser_code = None

        best_parser = parser_service.get_best_parser(user_id)
        if best_parser:
            parser_state = best_parser['state']
            logger.info(
                "[SmartParser] Using %s parser (id=%s) for user %s",
                parser_state, best_parser['id'], user_id,
            )

            if parser_state == 'LOCKED':
                try:
                    exec_globals: dict = {}
                    exec(best_parser['code'], exec_globals)
                    parse_fn = exec_globals.get('parse')
                    if callable(parse_fn):
                        _locked_parsed = parse_fn(flat_lines)
                    else:
                        _locked_parsed = None
                except Exception:
                    logger.warning("[SmartParser] Locked parser execution failed", exc_info=True)
                    _locked_parsed = None

                if has_meaningful_content(_locked_parsed):
                    parsed = normalize_dates(_locked_parsed)
                    parser_used = 'smart_locked'
                else:
                    logger.warning("[SmartParser] Locked parser returned no content, regenerating...")
                    best_parser = None

            if best_parser and parser_state == 'ACTIVE':
                result, final_code, sp_logs = parser_service.run_parser(
                    best_parser['id'], user_id, flat_lines,
                    provider=sp_provider, api_key=sp_api_key, model=sp_model,
                )
                if has_meaningful_content(result):
                    parsed = normalize_dates(result)
                    parser_used = 'smart_active'
                else:
                    logger.warning(
                        "[SmartParser] Active parser returned no content, falling back to heuristic"
                    )
                    parsed = parse_resume_from_extracted(extracted_data)

        if not best_parser and sp_provider and sp_api_key:
            logger.info("[SmartParser] Generating new parser for user %s", user_id)
            try:
                with open(pdf_path, 'rb') as pf:
                    pdf_bytes = pf.read()
                parser_id, code, gen_logs = parser_service.generate_and_store_parser(
                    user_id, flat_lines, sp_provider, sp_api_key, sp_model,
                    pdf_bytes=pdf_bytes,
                )
                result, final_code, sp_logs = parser_service.run_parser(
                    parser_id, user_id, flat_lines,
                    provider=sp_provider, api_key=sp_api_key, model=sp_model,
                )
                if has_meaningful_content(result):
                    parsed = normalize_dates(result)
                    parser_used = 'smart_generated'
                    generated_parser_code = final_code
                    logger.info("[SmartParser] Parser accepted (DRAFT id=%s)", parser_id)
                else:
                    logger.warning(
                        "[SmartParser] Parser returned only header fields %s, "
                        "falling back to heuristic",
                        list((result or {}).keys()),
                    )
                    parsed = parse_resume_from_extracted(extracted_data)
            except Exception as exc:
                ai_error_info = extract_ai_error(exc)
                logger.error(
                    "[SmartParser] Generation failed: %s",
                    ai_error_info['message'],
                    exc_info=True,
                )
                parsed = parse_resume_from_extracted(extracted_data)

        if parsed is None:
            parsed = parse_resume_from_extracted(extracted_data)

        if not parsed:
            return jsonify({
                "status": "error",
                "message": "Could not parse the PDF. Try providing an AI API key for better results.",
            }), 500

        parsed = clean_parsed_resume(parsed)

        confidence = score_parsed_resume(parsed)

        header = {
            "name": parsed.get('name', ''),
            "contact": parsed.get('contact', {}),
        }

        raw_headings = parsed.pop('_section_headings', {})
        section_names = {}
        for key, heading_text in raw_headings.items():
            section_names[key] = heading_text

        custom_sections = []
        for key in parsed:
            if key not in BUILTIN_KEYS:
                display_name = raw_headings.get(key, key.replace('_', ' ').upper())
                render_type = infer_render_type(parsed[key])
                custom_sections.append({
                    "key": key,
                    "display_name": display_name,
                    "render_type": render_type,
                })

        editable_data = strip_header(parsed, header)
        yaml_content = yaml.dump(editable_data, sort_keys=False, allow_unicode=True)

        response_payload = {
            "yaml": yaml_content,
            "header": header,
            "style": extracted_style,
            "custom_sections": custom_sections,
            "section_names": section_names,
            "confidence": confidence,
            "extraction_source": extraction_source,
            "parser_used": parser_used,
        }

        if generated_parser_code:
            response_payload["generated_parser_code"] = generated_parser_code

        if ai_error_info:
            response_payload["status"] = "ai_parse_failed"
            response_payload["ai_error"] = ai_error_info["message"]
            response_payload["ai_status_code"] = ai_error_info["status_code"]
        else:
            response_payload["status"] = "success"

        return jsonify(response_payload)

    except Exception as exc:
        logger.exception("upload_resume failed")
        return jsonify({"status": "error", "message": str(exc)}), 500


@bp.route('/api/ai_change_request', methods=['POST'])
@login_required
def ai_change_request():
    """Apply an AI-driven change request to the parsed YAML during onboarding review."""
    user_id = get_current_user_id()
    data = request.json
    yaml_content = data.get('yaml', '')
    change_request = data.get('change_request', '').strip()

    if not yaml_content or not change_request:
        return jsonify({
            "status": "error",
            "message": "YAML content and change request are required.",
        }), 400

    try:
        ai_provider, ai_api_key, ai_model = _resolve_ai_credentials(data, user_id)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    try:
        system_prompt = (
            "You are a resume content editor. You will receive a resume in YAML format "
            "and a user's change request.\n\n"
            "Apply the requested changes to the YAML content and return the MODIFIED YAML.\n\n"
            "Rules:\n"
            "- Return ONLY the modified YAML content, no explanation or markdown code fences.\n"
            "- Preserve the YAML structure and formatting.\n"
            "- Only modify what the user requested. Do not add, remove, or change anything else.\n"
            "- Keep all existing content intact unless the user explicitly asks to change it.\n"
            "- If the request is unclear, make the most reasonable interpretation."
        )

        user_msg = f"CURRENT YAML:\n{yaml_content}\n\nCHANGE REQUEST:\n{change_request}"
        response_text = call_llm(ai_provider, ai_api_key, system_prompt, user_msg, ai_model)

        modified_yaml = response_text.strip()
        if modified_yaml.startswith('```'):
            lines = modified_yaml.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            modified_yaml = '\n'.join(lines)

        try:
            yaml.safe_load(modified_yaml)
        except Exception:
            return jsonify({
                "status": "error",
                "message": "AI returned invalid YAML. Try rephrasing your request.",
            }), 400

        return jsonify({"status": "success", "yaml": modified_yaml})

    except Exception as exc:
        logger.exception("ai_change_request failed")
        return jsonify({"status": "error", "message": str(exc)}), 500


@bp.route('/api/search_section', methods=['POST'])
@login_required
def search_section():
    """Search for a missing section in the uploaded PDF."""
    user_id = get_current_user_id()
    data = request.json
    section_hint = data.get('section_hint', '').strip()

    if not section_hint:
        return jsonify({
            "status": "error",
            "message": "Please enter a section name to search for.",
        }), 400

    pdf_path = _onboarding_pdf_path(user_id)

    if not os.path.exists(pdf_path):
        return jsonify({
            "status": "error",
            "message": "No PDF uploaded. Please re-upload your resume.",
        }), 400

    try:
        search_result = _search_section_local(pdf_path, section_hint)

        if not search_result.get('found'):
            return jsonify({
                "status": "not_found",
                "message": f"Could not find a section matching '{section_hint}' in your PDF.",
            })

        section_lines = search_result.get('lines', [])
        text_lines = [line.get('text', '') for line in section_lines]
        line_meta = section_lines

        render_type, parsed = _smart_parse_section(text_lines, line_meta)

        section_key = _normalize_section_key(section_hint)
        if not section_key or section_key == 'other':
            section_key = section_hint.lower().replace(' ', '_')

        yaml_snippet = yaml.dump(
            {section_key: parsed}, sort_keys=False, allow_unicode=True,
        )

        raw_lines = '\n'.join(text_lines)

        return jsonify({
            "status": "found",
            "section_key": section_key,
            "heading": search_result.get('heading', section_hint),
            "yaml_snippet": yaml_snippet,
            "raw_lines": raw_lines,
            "render_type": render_type,
            "display_name": section_hint.upper(),
        })

    except Exception as exc:
        logger.exception("search_section failed")
        return jsonify({"status": "error", "message": str(exc)}), 500


@bp.route('/api/complete_onboarding', methods=['POST'])
@login_required
def complete_onboarding():
    """Save finalized resume data and mark onboarding complete."""
    user_id = get_current_user_id()
    if is_onboarding_complete(user_id):
        return jsonify({"status": "error", "message": "Onboarding already completed."}), 400

    data = request.json
    resume_yaml = data.get('resume', '')
    header = data.get('header', {})
    style = data.get('style', {})
    custom_sections = data.get('custom_sections', [])
    section_names = data.get('section_names', {})

    try:
        current_settings = get_user_settings(user_id)

        merged_header = current_settings['header'].copy()
        if header.get('name'):
            merged_header['name'] = header['name']
        if header.get('contact'):
            for key, val in header['contact'].items():
                if val:
                    merged_header.setdefault('contact', {})[key] = val

        merged_section_names = current_settings.get(
            'section_names', DEFAULT_SECTION_NAMES.copy(),
        )
        if section_names:
            merged_section_names.update(section_names)

        update_user_settings(
            user_id,
            header=merged_header,
            style=style,
            custom_sections=custom_sections,
            section_names=merged_section_names,
        )

        if resume_yaml.strip():
            full_data = merge_header(resume_yaml, merged_header)
            full_yaml = yaml.dump(full_data, sort_keys=False, allow_unicode=True)
            save_current_resume(user_id, full_yaml, source='upload', label='Initial upload')

        # PII no longer needed once YAML is saved
        pdf_path = _onboarding_pdf_path(user_id)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        mark_onboarding_complete(user_id)
        return jsonify({"status": "success", "message": "Setup complete!"})

    except Exception as exc:
        logger.exception("complete_onboarding failed")
        return jsonify({"status": "error", "message": str(exc)}), 500


@bp.route('/api/skip_onboarding', methods=['POST'])
@login_required
def skip_onboarding():
    """Skip onboarding and go straight to the editor."""
    user_id = get_current_user_id()
    if is_onboarding_complete(user_id):
        return jsonify({"status": "error", "message": "Onboarding already completed."}), 400

    mark_onboarding_complete(user_id)
    return jsonify({"status": "success", "message": "Onboarding skipped."})


@bp.route('/api/uploaded_pdf')
@login_required
def serve_uploaded_pdf():
    """Serve the uploaded onboarding PDF for in-browser viewing."""
    user_id = get_current_user_id()
    pdf_path = _onboarding_pdf_path(user_id)
    if os.path.exists(pdf_path):
        return send_file(pdf_path, mimetype='application/pdf')
    return jsonify({"status": "error", "message": "No PDF found"}), 404


@bp.route('/api/sandbox_status')
@login_required
def sandbox_status():
    """Return whether sandbox is available (always false in local mode)."""
    return jsonify({"available": False, "api_url": None})
