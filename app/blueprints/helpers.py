"""Shared helpers for blueprint routes."""

import re
import yaml
import os
from functools import wraps
from flask import session, redirect, url_for, request

from app.models import (
    get_user_settings, DEFAULT_SECTION_NAMES,
)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def get_current_user_id():
    return session.get('user_id')


def get_current_user_header():
    settings = get_user_settings(get_current_user_id())
    return settings.get('header', {})


def get_current_section_names():
    settings = get_user_settings(get_current_user_id())
    return settings.get('section_names', DEFAULT_SECTION_NAMES.copy())


def get_current_custom_sections():
    settings = get_user_settings(get_current_user_id())
    return settings.get('custom_sections', [])


def md_bold(text):
    """Convert **word** to <strong>word</strong>."""
    if not text:
        return text
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', str(text))


def merge_header(partial_data, header):
    """Merge user header into resume data."""
    if isinstance(partial_data, str):
        try:
            partial_data = yaml.safe_load(partial_data) or {}
        except Exception:
            partial_data = {}
    if not isinstance(partial_data, dict):
        partial_data = {}
    full_data = partial_data.copy()
    full_data.update(header)
    return full_data


def strip_header(full_data, header):
    """Remove header keys from resume data."""
    if isinstance(full_data, str):
        try:
            full_data = yaml.safe_load(full_data) or {}
        except Exception:
            full_data = {}
    if not isinstance(full_data, dict):
        return {}
    partial_data = full_data.copy()
    for key in header:
        if key in partial_data:
            del partial_data[key]
    return partial_data


# ---------------------------------------------------------------------------
# Post-processing helpers
# ---------------------------------------------------------------------------

BUILTIN_KEYS = {'name', 'contact', 'summary', 'education', 'technical_skills',
                'experience', 'projects', 'extracurricular'}

_CONTACT_PAT = re.compile(
    r'@|mailto:|tel:|tel\.|linkedin\.com|github\.com|https?://|www\.'
    r'|\+\d[\d\s\-()]{6,}',
    re.IGNORECASE,
)
_EDU_KEYWORDS = re.compile(
    r'university|college|school|institute|academy|polytechnic',
    re.IGNORECASE,
)
_BULLET_PREFIX = re.compile(r'^[\u2022\u2023\u25e6\-\*]\s*')


def infer_render_type(data):
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            if 'category' in data[0] and 'skills' in data[0]:
                return 'skills'
            _ENTRY_KEYS = ('company', 'role', 'institution', 'degree', 'date',
                           'name', 'event', 'award', 'title', 'description',
                           'organization', 'position', 'location')
            if any(k in data[0] for k in _ENTRY_KEYS):
                return 'entries'
        return 'bullets'
    if isinstance(data, dict) and 'bullets' in data:
        return 'bullets'
    return 'bullets'


def has_meaningful_content(parsed):
    if not isinstance(parsed, dict) or not parsed:
        return False
    _HEADER_KEYS = {'name', 'contact', '_section_headings', '_date_parsed'}

    def _entry_has_text(entry):
        if isinstance(entry, dict):
            return any(str(v).strip() for v in entry.values() if v)
        if isinstance(entry, str):
            return bool(entry.strip())
        return False

    for key, val in parsed.items():
        if key in _HEADER_KEYS:
            continue
        if isinstance(val, list) and any(_entry_has_text(e) for e in val):
            return True
        if isinstance(val, dict):
            if val.get('bullets') and any(str(b).strip() for b in val['bullets'] if b):
                return True
            if any(str(v).strip() for v in val.values() if v):
                return True
        if isinstance(val, str) and val.strip():
            return True
    return False


def clean_flat_list(items):
    if not items or not all(isinstance(i, str) for i in items):
        return items
    stripped = [i.strip() for i in items]
    bullet_count = sum(1 for s in stripped if _BULLET_PREFIX.match(s))
    is_bullet_list = bullet_count >= max(1, len(stripped) * 0.4)
    cleaned = []
    for s in stripped:
        if not s:
            continue
        if is_bullet_list:
            if _BULLET_PREFIX.match(s):
                cleaned.append(_BULLET_PREFIX.sub('', s).strip())
            else:
                if cleaned:
                    cleaned[-1] = cleaned[-1].rstrip() + ' ' + s
                else:
                    cleaned.append(s)
        else:
            cleaned.append(s)
    return [s for s in cleaned if s]


def clean_parsed_resume(parsed):
    if not isinstance(parsed, dict):
        return parsed
    result = dict(parsed)
    edu = result.get('education')
    if isinstance(edu, list):
        kept = []
        for entry in edu:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            degree = (entry.get('degree') or '').strip()
            institution = (entry.get('institution') or '').strip()
            desc = entry.get('description') or []
            desc_text = ' '.join(str(d) for d in desc) if isinstance(desc, list) else str(desc)
            if _CONTACT_PAT.search(desc_text) or _CONTACT_PAT.search(institution):
                if not _EDU_KEYWORDS.search(institution):
                    continue
            if not degree and not _EDU_KEYWORDS.search(institution):
                continue
            kept.append(entry)
        result['education'] = kept
    for key, val in result.items():
        if isinstance(val, list) and val:
            if isinstance(val[0], str):
                result[key] = clean_flat_list(val)
            elif isinstance(val[0], dict):
                for item in val:
                    if not isinstance(item, dict):
                        continue
                    for subkey in ('bullets', 'description'):
                        if isinstance(item.get(subkey), list):
                            item[subkey] = clean_flat_list(item[subkey])
        elif isinstance(val, dict):
            for subkey in ('bullets', 'description'):
                if isinstance(val.get(subkey), list):
                    val[subkey] = clean_flat_list(val[subkey])
    return result


def build_raw_text(extracted_data):
    parts = []
    for page in extracted_data.get('pages', []):
        for line in page.get('lines', []):
            text = line.get('text', '').strip()
            if text:
                parts.append(text)
    return '\n'.join(parts)


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}
