"""Versions blueprint: list, restore, tag versions."""

import json
from flask import Blueprint, request, jsonify

from app.blueprints.helpers import login_required, get_current_user_id
from app.models import list_resume_versions, update_version_tags
from app.services.resume import get_version, restore_version

bp = Blueprint('versions', __name__)


@bp.route('/api/versions', methods=['GET'])
@login_required
def list_versions():
    user_id = get_current_user_id()
    versions = list_resume_versions(user_id)
    for v in versions:
        if v.get('tags') and isinstance(v['tags'], str):
            v['tags'] = json.loads(v['tags'])
    return jsonify(versions)


@bp.route('/api/versions/restore', methods=['POST'])
@login_required
def restore():
    user_id = get_current_user_id()
    data = request.json or {}
    version_id = data.get('version_id')
    if not version_id:
        return jsonify({'error': 'version_id required'}), 400
    try:
        yaml_content = restore_version(version_id, user_id)
        return jsonify({'status': 'ok', 'yaml': yaml_content})
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@bp.route('/api/versions/<int:version_id>/tags', methods=['PATCH'])
@login_required
def update_tags(version_id):
    user_id = get_current_user_id()
    data = request.json or {}
    tags = data.get('tags', [])
    if not isinstance(tags, list):
        return jsonify({'error': 'tags must be a list'}), 400
    update_version_tags(version_id, user_id, tags)
    return jsonify({'status': 'ok', 'tags': tags})
