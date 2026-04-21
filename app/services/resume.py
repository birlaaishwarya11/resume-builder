"""
Resume service -- single source of truth for resume YAML.

Responsibilities:
- Read / write the current resume YAML (filesystem, per user)
- Persist every meaningful change as a version in the DB
- Restore from a previous version
"""

import os
import yaml

from app.models import (
    get_user_dir,
    save_resume_version,
    list_resume_versions,
    get_resume_version,
    update_version_tags,
)


def _resume_path(user_id: int) -> str:
    return os.path.join(get_user_dir(user_id), 'resume.yaml')


# ---------------------------------------------------------------------------
# Current resume (filesystem)
# ---------------------------------------------------------------------------

def get_current_resume(user_id: int) -> str | None:
    """Return the raw YAML string for the user's current resume, or None."""
    path = _resume_path(user_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def save_current_resume(
    user_id: int,
    yaml_content: str,
    source: str = 'manual_edit',
    label: str | None = None,
    tags: list | None = None,
) -> int:
    """Write the canonical resume file and snapshot it in the DB.

    Returns the new version id.
    """
    _validate_yaml(yaml_content)
    user_dir = get_user_dir(user_id)
    os.makedirs(user_dir, exist_ok=True)
    path = _resume_path(user_id)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)
    return save_resume_version(user_id, yaml_content, source=source, label=label, tags=tags)


def tag_version(version_id: int, user_id: int, tags: list) -> None:
    """Update tags on an existing resume version."""
    update_version_tags(version_id, user_id, tags)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def list_versions(user_id: int) -> list[dict]:
    """Return version metadata (no yaml_content), newest first."""
    return list_resume_versions(user_id)


def get_version(version_id: int, user_id: int) -> dict | None:
    """Return a full version dict including yaml_content."""
    return get_resume_version(version_id, user_id)


def restore_version(version_id: int, user_id: int) -> str:
    """Restore a previous version as the current resume.

    Returns the restored YAML string.
    """
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
    """Safely parse a YAML string to a dict."""
    if not yaml_content or not yaml_content.strip():
        return {}
    result = yaml.safe_load(yaml_content)
    return result if isinstance(result, dict) else {}


def dump_yaml(data: dict) -> str:
    """Dump a dict to a YAML string."""
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
