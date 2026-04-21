"""Parsers blueprint: parser lifecycle management."""

from flask import Blueprint, request, jsonify

from app.blueprints.helpers import login_required, get_current_user_id
import app.services.parser as parser_service

bp = Blueprint('parsers', __name__)


@bp.route('/api/parser/list', methods=['GET'])
@login_required
def list_parsers():
    user_id = get_current_user_id()
    parsers = parser_service.list_user_parsers(user_id)
    return jsonify(parsers)


@bp.route('/api/parser/activate', methods=['POST'])
@login_required
def activate():
    user_id = get_current_user_id()
    data = request.json or {}
    parser_id = data.get('parser_id')
    if not parser_id:
        return jsonify({'error': 'parser_id required'}), 400
    try:
        parser_service.activate_parser(parser_id, user_id)
        return jsonify({'status': 'ok'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/parser/lock', methods=['POST'])
@login_required
def lock():
    user_id = get_current_user_id()
    data = request.json or {}
    parser_id = data.get('parser_id')
    if not parser_id:
        return jsonify({'error': 'parser_id required'}), 400
    try:
        parser_service.confirm_and_lock(parser_id, user_id)
        return jsonify({'status': 'ok'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/parser/unlock', methods=['POST'])
@login_required
def unlock():
    user_id = get_current_user_id()
    data = request.json or {}
    parser_id = data.get('parser_id')
    if not parser_id:
        return jsonify({'error': 'parser_id required'}), 400
    try:
        parser_service.unlock_parser(parser_id, user_id)
        return jsonify({'status': 'ok'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/parser/discard', methods=['POST'])
@login_required
def discard():
    user_id = get_current_user_id()
    data = request.json or {}
    parser_id = data.get('parser_id')
    if not parser_id:
        return jsonify({'error': 'parser_id required'}), 400
    try:
        parser_service.discard_parser(parser_id, user_id)
        return jsonify({'status': 'ok'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
