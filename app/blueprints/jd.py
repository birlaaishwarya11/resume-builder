"""JD blueprint: analyze, generate, apply, find job descriptions."""

import json
import traceback

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, request, jsonify

from app.blueprints.helpers import login_required, get_current_user_id
from app.orchestrator import get_orchestrator
from app.services.resume import get_current_resume
import app.services.jd as jd_service
import app.agents.jd_resume as jd_resume_agent
import app.agents.jd_finder as jd_finder_agent

bp = Blueprint('jd', __name__)


@bp.route('/api/jd_analyze', methods=['POST'])
@login_required
def jd_analyze():
    """Analyze current resume against a JD. Returns match score + suggestions."""
    user_id = get_current_user_id()
    data = request.json or {}
    jd_text = (data.get('jd_text') or '').strip()
    if not jd_text:
        return jsonify({'error': 'jd_text is required'}), 400

    try:
        orch = get_orchestrator(data, user_id)
        session_id, result, logs = orch.analyze_jd(jd_text)
        return jsonify({
            'status': 'success',
            'session_id': session_id,
            'match_score': result['match_score'],
            'suggestions': result['suggestions'],
            'base_version_id': result.get('base_version_id'),
            'base_version_label': result.get('base_version_label'),
            'logs': logs,
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        from app.services.ai import extract_ai_error
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


@bp.route('/api/jd_apply', methods=['POST'])
@login_required
def jd_apply():
    """Apply selected suggestions from a JD session."""
    user_id = get_current_user_id()
    data = request.json or {}
    session_id = data.get('session_id')
    suggestion_ids = data.get('suggestion_ids', [])

    if not session_id or not suggestion_ids:
        return jsonify({'error': 'session_id and suggestion_ids required'}), 400

    try:
        orch = get_orchestrator(data, user_id)
        new_yaml, version_id, logs = orch.apply_suggestions(session_id, suggestion_ids)
        return jsonify({
            'status': 'success',
            'yaml': new_yaml,
            'version_id': version_id,
            'logs': logs,
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        from app.services.ai import extract_ai_error
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


@bp.route('/api/jd_generate', methods=['POST'])
@login_required
def jd_generate():
    """Full 7-stage agent pipeline: generate tailored resume from JD."""
    user_id = get_current_user_id()
    data = request.json or {}
    jd_text = (data.get('jd_text') or '').strip()
    if not jd_text:
        return jsonify({'error': 'jd_text is required'}), 400

    try:
        orch = get_orchestrator(data, user_id)
        target_score = data.get('target_score', 90)
        result = orch.generate_for_jd(jd_text, target_score=target_score)
        return jsonify({'status': 'success', **result})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        from app.services.ai import extract_ai_error
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


@bp.route('/api/jd_find', methods=['POST'])
@login_required
def jd_find():
    """Search for JD (by company+role or URL) and run full pipeline."""
    user_id = get_current_user_id()
    data = request.json or {}
    mode = data.get('mode', 'search')
    company = (data.get('company') or '').strip()
    role = (data.get('role') or '').strip()
    url = (data.get('url') or '').strip()

    try:
        orch = get_orchestrator(data, user_id)

        if mode == 'url' and url:
            # Fetch page content
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; ResumeBuilder/1.0)'
            })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            page_text = soup.get_text(separator='\n', strip=True)

            # Extract JD from page
            jd_text = jd_finder_agent.extract_jd_from_html(
                page_text, orch.provider, orch.api_key, orch.model
            )
            if not jd_text:
                return jsonify({'error': 'Could not extract a job description from that URL'}), 400

        elif mode == 'search' and company and role:
            # Build search query -- caller would need to handle actual web search
            query = jd_finder_agent.build_search_query(company, role)
            return jsonify({
                'error': 'Web search not available in this deployment. '
                         'Please paste the JD URL directly.',
                'search_query': query,
            }), 400

        else:
            return jsonify({'error': 'Provide url or company+role'}), 400

        # Run the full pipeline with extracted JD
        result = orch.generate_for_jd(jd_text)
        result['jd_text'] = jd_text
        result['jd_url'] = url
        result['jd_source'] = mode
        return jsonify({'status': 'success', **result})

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        from app.services.ai import extract_ai_error
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500


@bp.route('/api/jd_agent/diff', methods=['GET'])
@login_required
def jd_agent_diff():
    """Compare current resume vs last agent-generated version."""
    user_id = get_current_user_id()
    agent_version = jd_resume_agent.get_last_agent_version(user_id)
    if not agent_version:
        return jsonify({'has_changes': False, 'message': 'No agent version found'})

    current_yaml = get_current_resume(user_id)
    if not current_yaml:
        return jsonify({'has_changes': False, 'message': 'No current resume'})

    changes = jd_resume_agent.diff_versions(agent_version['yaml_content'], current_yaml)
    return jsonify({
        'has_changes': len(changes) > 0,
        'changes': changes,
        'agent_version_id': agent_version['id'],
    })


@bp.route('/api/jd_agent/learn', methods=['POST'])
@login_required
def jd_agent_learn():
    """Store learning from user edits to agent-generated resume."""
    user_id = get_current_user_id()
    data = request.json or {}
    reason = (data.get('reason') or '').strip()
    tags = data.get('tags', [])
    changes = data.get('changes', [])

    if not reason:
        return jsonify({'error': 'reason is required'}), 400

    jd_resume_agent.save_learning(user_id, tags, changes, reason)
    return jsonify({'status': 'ok'})


@bp.route('/api/jd_sessions', methods=['GET'])
@login_required
def jd_sessions():
    """List past JD analysis sessions."""
    user_id = get_current_user_id()
    sessions = jd_service.list_sessions(user_id)
    return jsonify(sessions)


@bp.route('/api/match_jd', methods=['POST'])
@login_required
def match_jd():
    """Quick ATS score of current resume against JD."""
    user_id = get_current_user_id()
    data = request.json or {}
    jd_text = (data.get('jd_text') or '').strip()
    if not jd_text:
        return jsonify({'error': 'jd_text is required'}), 400

    try:
        orch = get_orchestrator(data, user_id)
        result = orch.quick_ats_score(jd_text)
        return jsonify({'status': 'success', **result})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        from app.services.ai import extract_ai_error
        err = extract_ai_error(e)
        return jsonify({'error': err['message']}), err.get('status_code') or 500
