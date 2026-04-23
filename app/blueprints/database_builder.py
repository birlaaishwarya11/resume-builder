"""Database-builder blueprint.

Three POST endpoints for the wizard flow plus a GET for the question list:

    POST /api/db_builder/extract     -- crawl links + LLM-extract items + moments
    POST /api/db_builder/answer      -- run a single Q&A pass into items + moments
    POST /api/db_builder/consolidate -- render items + moments to markdown
    POST /api/db_builder/save        -- save markdown into user_documents
    GET  /api/db_builder/questions   -- the static Q&A prompt list

Phase 1 is backend-only; the wizard UI is wired in Phase 3.
"""

import logging
import traceback

from flask import Blueprint, jsonify, render_template, request

from app.agents import database_builder as builder
from app.agents.safety import (
    MAX_BUILD_INPUT_BYTES,
    MAX_FETCHES_PER_BUILD,
    MAX_LLM_CALLS_PER_BUILD,
)
from app.blueprints.databases import MAX_DOCUMENT_BYTES
from app.blueprints.helpers import get_current_user_id, login_required
from app.orchestrator import resolve_ai_credentials
from app.services import documents
from app.services.ai import extract_ai_error

logger = logging.getLogger(__name__)
bp = Blueprint('database_builder', __name__)

_VALID_SAVE_MODES = ('replace', 'append')


@bp.route('/database-builder')
@login_required
def database_builder_page():
    """Render the 3-step Database Builder wizard UI."""
    return render_template('database_builder.html')


@bp.route('/api/db_builder/questions', methods=['GET'])
@login_required
def questions():
    """Static list of Q&A prompts the wizard shows the user.

    The blueprint serves them so the UI stays in sync with the backend
    expectations of ``/api/db_builder/answer``.
    """
    return jsonify({
        'questions': builder.ANSWER_QUESTIONS,
        'budget': {
            'fetches': MAX_FETCHES_PER_BUILD,
            'llm_calls': MAX_LLM_CALLS_PER_BUILD,
            'bytes_in': MAX_BUILD_INPUT_BYTES,
        },
    })


@bp.route('/api/db_builder/extract', methods=['POST'])
@login_required
def extract():
    """Crawl portfolio + project URLs and return extracted items + moments."""
    user_id = get_current_user_id()
    data = request.json or {}

    portfolio_url = (data.get('portfolio_url') or '').strip() or None
    project_urls = data.get('project_urls') or []
    if not isinstance(project_urls, list):
        return jsonify({'error': 'project_urls must be a list'}), 400
    project_urls = [str(u).strip() for u in project_urls if str(u).strip()]

    github_pat = (data.get('github_pat') or '').strip() or None

    if not portfolio_url and not project_urls:
        return jsonify({
            'error': 'Provide portfolio_url and/or project_urls',
        }), 400

    try:
        provider, api_key, model = resolve_ai_credentials(data, user_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        result = builder.build(
            seed_url=portfolio_url,
            project_urls=project_urls,
            github_pat=github_pat,
            provider=provider, api_key=api_key, model=model,
        )
        return jsonify({'status': 'success', **result})
    except Exception as e:
        traceback.print_exc()
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


@bp.route('/api/db_builder/answer', methods=['POST'])
@login_required
def answer():
    """Run one LLM pass over a free-text answer to a wizard question."""
    user_id = get_current_user_id()
    data = request.json or {}

    question_id = (data.get('question_id') or '').strip()
    answer_text = (data.get('answer') or '').strip()
    if not question_id or not answer_text:
        return jsonify({'error': 'question_id and answer are required'}), 400

    valid_ids = {q['id'] for q in builder.ANSWER_QUESTIONS}
    if question_id not in valid_ids:
        return jsonify({'error': f'Unknown question_id: {question_id}'}), 400

    try:
        provider, api_key, model = resolve_ai_credentials(data, user_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    # One-shot budget per answer: a single LLM call.
    budget = builder.BuildBudget(fetches=0, llm_calls=1, bytes_in=64 * 1024)
    try:
        items, moments = builder.items_and_moments_from_answer(
            question_id, answer_text, provider, api_key, model, budget,
        )
        return jsonify({
            'status': 'success',
            'items': items,
            'moments': moments,
            'budget': budget.usage(),
        })
    except Exception as e:
        traceback.print_exc()
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


@bp.route('/api/db_builder/consolidate', methods=['POST'])
@login_required
def consolidate():
    """Render items + moments to markdown for preview before save.

    Pure-Python; no LLM call, no auth-key required.
    """
    data = request.json or {}
    items = data.get('items') or []
    moments = data.get('moments') or []
    if not isinstance(items, list) or not isinstance(moments, list):
        return jsonify({'error': 'items and moments must be lists'}), 400

    items = [i for i in items if isinstance(i, dict)]
    moments = [m for m in moments if isinstance(m, dict)]

    include_off_topic = bool(data.get('include_off_topic', False))
    candidate_md = builder.consolidate_candidate_db(
        items, include_off_topic=include_off_topic,
    )
    cl_md = builder.consolidate_cl_db(
        moments, include_off_topic=include_off_topic,
    )
    return jsonify({
        'status': 'success',
        'candidate_db_md': candidate_md,
        'cover_letter_db_md': cl_md,
    })


@bp.route('/api/db_builder/save', methods=['POST'])
@login_required
def save():
    """Persist the consolidated markdown into ``user_documents``.

    Modes:
        replace -- overwrite the existing column entirely.
        append  -- append a new section to the bottom of the existing column.
    """
    user_id = get_current_user_id()
    data = request.json or {}
    candidate_md = data.get('candidate_db_md') or ''
    cl_md = data.get('cover_letter_db_md') or ''
    mode = (data.get('mode') or 'replace').strip().lower()
    if mode not in _VALID_SAVE_MODES:
        return jsonify({
            'error': f'mode must be one of {_VALID_SAVE_MODES}',
        }), 400
    if not isinstance(candidate_md, str) or not isinstance(cl_md, str):
        return jsonify({'error': 'candidate_db_md and cover_letter_db_md must be strings'}), 400

    saved = {}
    for label, content, getter, setter in (
        ('candidate', candidate_md,
         documents.get_candidate_database, documents.save_candidate_database),
        ('cover_letter', cl_md,
         documents.get_cover_letter_database, documents.save_cover_letter_database),
    ):
        if not content.strip():
            continue
        if mode == 'append':
            existing = getter(user_id) or ''
            sep = '\n\n---\n\n' if existing.strip() else ''
            content = existing + sep + content
        if len(content.encode('utf-8')) > MAX_DOCUMENT_BYTES:
            return jsonify({
                'error': f'{label} document would exceed '
                         f'{MAX_DOCUMENT_BYTES // 1024} KB after {mode}',
            }), 413
        setter(user_id, content)
        saved[label] = len(content.encode('utf-8'))

    return jsonify({'status': 'success', 'mode': mode, 'saved_bytes': saved})
