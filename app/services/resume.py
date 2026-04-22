"""
Resume service -- single source of truth for resume YAML.

Responsibilities:
- Read / write the current resume YAML (Postgres, per user)
- Persist every meaningful change as a version in the DB
- Restore from a previous version
"""

import yaml

from app.models import (
    save_resume_version,
    list_resume_versions,
    get_resume_version,
    update_version_tags,
)
from app.services import documents


# ---------------------------------------------------------------------------
# Current resume (DB-backed)
# ---------------------------------------------------------------------------

def get_current_resume(user_id: int) -> str | None:
    """Return the raw YAML string for the user's current resume, or None."""
    content = documents.get_resume_yaml(user_id)
    return content if content else None


def save_current_resume(
    user_id: int,
    yaml_content: str,
    source: str = 'manual_edit',
    label: str | None = None,
    tags: list | None = None,
) -> int:
    """Write the canonical resume to DB and snapshot it as a version.

    Returns the new version id.
    """
    _validate_yaml(yaml_content)
    documents.save_resume_yaml(user_id, yaml_content)
    return save_resume_version(user_id, yaml_content, source=source, label=label, tags=tags)


def tag_version(version_id: int, user_id: int, tags: list) -> None:
    update_version_tags(version_id, user_id, tags)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def list_versions(user_id: int) -> list[dict]:
    """Return version metadata (no yaml_content), newest first."""
    return list_resume_versions(user_id)


def get_version(version_id: int, user_id: int) -> dict | None:
    return get_resume_version(version_id, user_id)


def restore_version(version_id: int, user_id: int) -> str:
    """Restore a previous version as the current resume. Returns the YAML."""
    version = get_resume_version(version_id, user_id)
    if not version:
        raise ValueError(f"Version {version_id} not found for user {user_id}")
    yaml_content = version['yaml_content']
    save_current_resume(user_id, yaml_content, source='manual_edit',
                        label=f'Restored from version {version_id}')
    return yaml_content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_yaml(yaml_content: str) -> None:
    try:
        yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e


def parse_yaml(yaml_content: str) -> dict:
    if not yaml_content or not yaml_content.strip():
        return {}
    result = yaml.safe_load(yaml_content)
    return result if isinstance(result, dict) else {}


def dump_yaml(data: dict) -> str:
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
