"""
Parser service -- manages the lifecycle of per-user resume parsers.

State machine: DRAFT -> ACTIVE -> LOCKED
"""

import hashlib

import app.parsers.smart as sp
from app.models import (
    create_parser,
    get_parser_by_id,
    get_active_parser,
    get_draft_parser,
    list_parsers,
    update_parser_state,
    update_parser_code,
    lock_parser,
    delete_parser,
)

PARSER_STATES = ('DRAFT', 'ACTIVE', 'LOCKED')


# ---------------------------------------------------------------------------
# Parser creation / generation
# ---------------------------------------------------------------------------

def generate_and_store_parser(user_id, lines, provider, api_key,
                              model=None, pdf_bytes=None):
    """Generate a parse() function via LLM and store it as a DRAFT parser.

    Returns: (parser_id, code, logs)
    """
    logs = ['Generating parser code via LLM...']
    code = sp.generate_parser_code(lines, provider, api_key, model)
    logs.append(f'Parser code generated ({len(code)} chars)')

    pdf_hash = _hash_pdf(pdf_bytes) if pdf_bytes else None
    parser_id = create_parser(
        user_id=user_id, code=code, state='DRAFT', source_pdf_hash=pdf_hash,
    )
    logs.append(f'Parser stored as DRAFT (id={parser_id})')
    return parser_id, code, logs


def run_parser(parser_id, user_id, lines,
               provider=None, api_key=None, model=None):
    """Execute a stored parser against extracted lines.

    Returns: (result_dict or None, final_code, logs)
    """
    parser = get_parser_by_id(parser_id)
    if not parser or parser['user_id'] != user_id:
        return None, '', [f'Parser {parser_id} not found or access denied']

    result, final_code, logs = sp.run_parser(lines, parser['code'], provider, api_key, model)

    if final_code and final_code != parser['code']:
        update_parser_code(parser_id, final_code)
        logs.append('Auto-fixed parser code persisted')

    return result, final_code, logs


def refine_parser(parser_id, user_id, change_request, lines,
                  provider, api_key, model=None):
    """Ask the LLM to modify an existing parser and re-run it.

    Returns: (new_code, logs)
    """
    parser = get_parser_by_id(parser_id)
    if not parser or parser['user_id'] != user_id:
        return '', ['Parser not found or access denied']

    logs = ['Refining parser via LLM...']
    new_code = sp.refine_parser_code(parser['code'], change_request, provider, api_key, model)
    update_parser_code(parser_id, new_code)
    logs.append('Refined code stored')
    return new_code, logs


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def activate_parser(parser_id, user_id):
    parser = _get_owned(parser_id, user_id)
    if parser['state'] == 'LOCKED':
        raise ValueError('Cannot demote a LOCKED parser to ACTIVE. Unlock first.')
    update_parser_state(parser_id, 'ACTIVE')


def confirm_and_lock(parser_id, user_id):
    _get_owned(parser_id, user_id)
    lock_parser(user_id, parser_id)


def unlock_parser(parser_id, user_id):
    parser = _get_owned(parser_id, user_id)
    if parser['state'] != 'LOCKED':
        raise ValueError('Parser is not LOCKED')
    update_parser_state(parser_id, 'ACTIVE')


def discard_parser(parser_id, user_id):
    _get_owned(parser_id, user_id)
    delete_parser(parser_id, user_id)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_best_parser(user_id):
    return get_active_parser(user_id)


def get_current_draft(user_id):
    return get_draft_parser(user_id)


def list_user_parsers(user_id):
    return list_parsers(user_id)


def get_parser(parser_id, user_id):
    parser = get_parser_by_id(parser_id)
    if not parser or parser['user_id'] != user_id:
        return None
    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_owned(parser_id, user_id):
    parser = get_parser_by_id(parser_id)
    if not parser or parser['user_id'] != user_id:
        raise ValueError(f'Parser {parser_id} not found or access denied')
    return parser


def _hash_pdf(pdf_bytes):
    return hashlib.sha256(pdf_bytes).hexdigest()


def resolve_credentials(user_provider=None, user_api_key=None, user_model=None):
    return sp.resolve_parser_credentials(user_provider, user_api_key, user_model)
