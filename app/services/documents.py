"""
User documents service -- thin facade over DB-backed per-user text blobs.

All seven per-user documents (resume YAML, cover-letter draft, four markdown
databases, and the resume-learnings log) live as TEXT columns on the
user_documents table. Callers should use the field-specific helpers below
instead of touching the DB directly.
"""

from app.models import get_document, save_document, get_all_documents, DOCUMENT_FIELDS


# Cap on how large the append-only learnings log can grow per user.
# When exceeded, we trim oldest entries (everything before the first "## Learning:"
# boundary past the cap offset) on next append.
LEARNINGS_MAX_BYTES = 64 * 1024


# ---------------------------------------------------------------------------
# Resume YAML
# ---------------------------------------------------------------------------

def get_resume_yaml(user_id: int) -> str:
    return get_document(user_id, 'resume_yaml')


def save_resume_yaml(user_id: int, yaml_text: str) -> None:
    save_document(user_id, 'resume_yaml', yaml_text)


# ---------------------------------------------------------------------------
# Cover letter draft YAML
# ---------------------------------------------------------------------------

def get_cover_letter_draft(user_id: int) -> str:
    return get_document(user_id, 'cover_letter_draft_yaml')


def save_cover_letter_draft(user_id: int, yaml_text: str) -> None:
    save_document(user_id, 'cover_letter_draft_yaml', yaml_text)


# ---------------------------------------------------------------------------
# Markdown databases
# ---------------------------------------------------------------------------

def get_candidate_database(user_id: int) -> str:
    return get_document(user_id, 'candidate_database')


def save_candidate_database(user_id: int, content: str) -> None:
    save_document(user_id, 'candidate_database', content)


def get_resume_rules(user_id: int) -> str:
    return get_document(user_id, 'resume_rules')


def save_resume_rules(user_id: int, content: str) -> None:
    save_document(user_id, 'resume_rules', content)


def get_cover_letter_database(user_id: int) -> str:
    return get_document(user_id, 'cover_letter_database')


def save_cover_letter_database(user_id: int, content: str) -> None:
    save_document(user_id, 'cover_letter_database', content)


def get_cover_letter_rules(user_id: int) -> str:
    return get_document(user_id, 'cover_letter_rules')


def save_cover_letter_rules(user_id: int, content: str) -> None:
    save_document(user_id, 'cover_letter_rules', content)


# ---------------------------------------------------------------------------
# Resume learnings (append-only, size-capped)
# ---------------------------------------------------------------------------

def get_resume_learnings(user_id: int) -> str:
    return get_document(user_id, 'resume_learnings')


def append_resume_learnings(user_id: int, entry: str,
                            header: str = "# Resume Generation Learnings\n\n") -> None:
    """Append an entry to the learnings log, trimming oldest content if capped.

    Trimming keeps the header, drops oldest `## Learning:` blocks until under
    the byte cap. If the entry itself exceeds the cap, we keep only the header
    plus this entry (truncated).
    """
    existing = get_document(user_id, 'resume_learnings') or header
    combined = existing + entry

    if len(combined.encode('utf-8')) <= LEARNINGS_MAX_BYTES:
        save_document(user_id, 'resume_learnings', combined)
        return

    # Trim oldest "## Learning:" blocks, preserving the header.
    body = combined
    if body.startswith(header):
        body = body[len(header):]

    blocks = body.split('\n## Learning:')
    # blocks[0] is either empty or content before the first learning.
    learnings = ['## Learning:' + b for b in blocks[1:]]

    # Drop oldest entries until we fit.
    while learnings and len((header + '\n'.join(learnings)).encode('utf-8')) > LEARNINGS_MAX_BYTES:
        learnings.pop(0)

    trimmed = header + '\n'.join(learnings) if learnings else header + entry
    # Hard cap in case a single entry is larger than the budget.
    if len(trimmed.encode('utf-8')) > LEARNINGS_MAX_BYTES:
        trimmed = trimmed.encode('utf-8')[:LEARNINGS_MAX_BYTES].decode('utf-8', errors='ignore')
    save_document(user_id, 'resume_learnings', trimmed)


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------

def get_all(user_id: int) -> dict:
    return get_all_documents(user_id)


__all__ = [
    'DOCUMENT_FIELDS',
    'LEARNINGS_MAX_BYTES',
    'get_resume_yaml', 'save_resume_yaml',
    'get_cover_letter_draft', 'save_cover_letter_draft',
    'get_candidate_database', 'save_candidate_database',
    'get_resume_rules', 'save_resume_rules',
    'get_cover_letter_database', 'save_cover_letter_database',
    'get_cover_letter_rules', 'save_cover_letter_rules',
    'get_resume_learnings', 'append_resume_learnings',
    'get_all',
]
