"""
Smart parser: LLM-generated resume parser with local restricted execution
and retry logic.

Pipeline:
  1. generate_parser_code()  -> LLM writes parse(lines) Python function
  2. run_parser()            -> executes code locally with restricted builtins
  3. normalize_dates()       -> normalises date strings across the parsed dict
"""

import os
import re
import json

# Server-side parser-gen credentials (optional)
PARSER_GEN_API_KEY = os.environ.get('PARSER_GEN_API_KEY', '')
PARSER_GEN_PROVIDER = os.environ.get('PARSER_GEN_PROVIDER', 'anthropic')
PARSER_GEN_MODEL = os.environ.get('PARSER_GEN_MODEL', 'claude-sonnet-4-6')

SAMPLE_LINES = 60
MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_GENERATE_PROMPT = """\
You are an expert Python developer specialising in resume parsing.

I will give you a sample of lines extracted from a PDF resume. Each line is a dict:
  {{"text": str, "size": float, "bold": bool}}

Your task: write a Python function called `parse` with this signature:

    def parse(lines: list[dict]) -> dict:

The function MUST return a dict using EXACTLY the top-level keys and inner field
names shown below. Do NOT invent new top-level keys or new field names inside
entries. Map every piece of content to the closest existing field. If something
genuinely does not fit any field, drop it.

Top-level keys (omit any that have no data):

    name               str
    contact            dict (see schema below)
    summary            str
    education          list of education entries
    experience         list of experience entries
    technical_skills   list of {{category, skills}} dicts
    projects           list of project entries
    extracurricular    list of {{title, bullets}} dicts
    _section_headings  dict mapping each emitted top-level section key
                       to its EXACT heading text as it appears in the PDF

Schemas:

    contact = {{
        "email", "phone", "location",
        "linkedin", "github",
        "portfolio_url", "portfolio_label"
    }}

    education entry = {{
        "institution", "degree", "location", "date",
        "gpa", "honors", "coursework"
    }}

    experience entry = {{
        "company", "role", "location", "date",
        "bullets": [str, ...]
    }}

    project entry = {{
        "name", "subtitle", "event", "award",
        "date", "url", "link_url", "link_text",
        "bullets": [str, ...]
    }}

    extracurricular entry = {{
        "title",
        "bullets": [str, ...]
    }}

For any section whose heading does NOT match the canonical sections above,
emit it under a top-level key derived from the heading (lowercased, words
joined by underscores) and use this SAME entry shape for every entry in it:

    custom entry = {{
        "name", "subtitle", "date", "location",
        "event", "award", "url", "link_url", "link_text",
        "bullets": [str, ...]
    }}

Rules:
- NO import statements -- only Python builtins are available (re, json are pre-imported).
- Use size and bold metadata to identify section headings for THIS specific resume.
- Extract ALL content; do not summarise or omit any bullet point or detail.
- Every entry MUST carry a non-empty primary identifier
  (institution / company / name / title for its section) AND a `bullets`
  list (empty list `[]` if there are no bullets).
- Omit fields with no data; do NOT emit empty strings.
- Normalise "Present"/"Current"/"Now"/"ongoing" in date strings to "Present".
- Return an empty dict on total failure (wrap risky code in try/except).
- The function must be completely self-contained.

Here are the first {n} lines of the resume (JSON):

{lines_json}

Respond with ONLY the Python function -- no markdown fences, no explanation.
"""

_FIX_PROMPT = """\
The following Python parser function raised an error when executed.

ERROR:
{error}

ORIGINAL CODE:
{code}

Fix the bug and return ONLY the corrected Python function (no markdown fences).
"""

_REFINE_PROMPT = """\
Below is a Python resume parser function. The user wants to change something about it.

USER REQUEST:
{change_request}

CURRENT CODE:
{code}

Return ONLY the updated Python function (no markdown fences).
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(provider, api_key, prompt, model=None):
    from app.services.ai import call_llm
    return call_llm(provider, api_key, '', prompt, model)


def _clean_code(raw):
    if not raw:
        return ''
    raw = raw.strip()
    raw = re.sub(r'^```(?:python)?\n?', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\n?```$', '', raw)
    return raw.strip()


# ---------------------------------------------------------------------------
# Parser generation
# ---------------------------------------------------------------------------

def resolve_parser_credentials(user_provider=None, user_api_key=None, user_model=None):
    if user_api_key and user_api_key.strip():
        return (user_provider or 'anthropic', user_api_key.strip(), user_model or None)
    if PARSER_GEN_API_KEY and PARSER_GEN_API_KEY.strip():
        return (PARSER_GEN_PROVIDER, PARSER_GEN_API_KEY.strip(), PARSER_GEN_MODEL)
    return None, None, None


def generate_parser_code(lines, provider, api_key, model=None):
    sample = lines[:SAMPLE_LINES]
    prompt = _GENERATE_PROMPT.format(
        n=len(sample),
        lines_json=json.dumps(sample, indent=2, ensure_ascii=False),
    )
    raw = _call_llm(provider, api_key, prompt, model)
    return _clean_code(raw)


def refine_parser_code(code, change_request, provider, api_key, model=None):
    prompt = _REFINE_PROMPT.format(change_request=change_request, code=code)
    raw = _call_llm(provider, api_key, prompt, model)
    return _clean_code(raw)


# ---------------------------------------------------------------------------
# Local execution (restricted builtins)
# ---------------------------------------------------------------------------

def _run_local(lines, code):
    """Execute parse(lines) locally with restricted builtins."""
    SAFE_BUILTINS = {
        '__builtins__': {
            'len': len, 'range': range, 'enumerate': enumerate,
            'zip': zip, 'dict': dict, 'list': list, 'set': set,
            'tuple': tuple, 'str': str, 'int': int, 'float': float,
            'bool': bool, 'isinstance': isinstance, 'hasattr': hasattr,
            'getattr': getattr, 'sorted': sorted, 'reversed': reversed,
            'min': min, 'max': max, 'sum': sum, 'abs': abs,
            'any': any, 'all': all, 'filter': filter, 'map': map,
            'print': print, 'repr': repr, 'type': type,
            'None': None, 'True': True, 'False': False,
            'Exception': Exception, 'ValueError': ValueError,
            'KeyError': KeyError, 'IndexError': IndexError,
        }
    }
    namespace = {'re': __import__('re'), 'json': __import__('json')}
    namespace.update(SAFE_BUILTINS)
    try:
        exec(code, namespace)
        result = namespace['parse'](lines)
        return result, None
    except Exception as e:
        return None, str(e)


def run_parser(lines, code, provider=None, api_key=None, model=None):
    """Run the generated parser with retry logic on errors.

    Returns: (result_dict_or_None, final_code_str, logs_list)
    """
    current_code = code
    all_logs = []

    for attempt in range(MAX_RETRIES + 1):
        result, error = _run_local(lines, current_code)

        if result is not None:
            all_logs.append("Parser executed successfully")
            return result, current_code, all_logs

        all_logs.append(f"Attempt {attempt + 1} failed: {error[:200] if error else 'unknown'}")

        if attempt < MAX_RETRIES and error and provider and api_key:
            all_logs.append("Asking LLM to fix the error...")
            try:
                fix_prompt = _FIX_PROMPT.format(error=error[:600], code=current_code)
                fixed_raw = _call_llm(provider, api_key, fix_prompt, model)
                current_code = _clean_code(fixed_raw)
                all_logs.append("Received fix from LLM, retrying...")
            except Exception as fix_err:
                all_logs.append(f"Fix LLM call failed: {fix_err}")
                break
        else:
            break

    all_logs.append(f"All attempts failed: {error}")
    return None, current_code, all_logs


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
    'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
    'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
}
_CURRENT_TOKENS = {'present', 'current', 'now', 'ongoing', 'today', 'till date', 'to date'}


def _parse_date_token(token):
    t = token.strip().lower().rstrip('.')
    if t in _CURRENT_TOKENS:
        return 'Present'
    m = re.match(r"([a-z]{3})['\s]?(\d{2,4})", t)
    if m:
        mon = _MONTH_MAP.get(m.group(1))
        yr = m.group(2)
        if len(yr) == 2:
            yr = ('20' if int(yr) < 70 else '19') + yr
        if mon:
            return f"{yr}-{mon}"
    m = re.match(r'^(\d{4})$', t)
    if m:
        return m.group(1)
    m = re.match(r'q([1-4])\s*(\d{4})', t)
    if m:
        qmon = {'1': '01', '2': '04', '3': '07', '4': '10'}[m.group(1)]
        return f"{m.group(2)}-{qmon}"
    return None


def normalize_date_string(date_str):
    if not date_str or not isinstance(date_str, str):
        return None
    raw = date_str.strip()
    parts = re.split(r'\s*[--\-]\s*|\s+to\s+', raw, maxsplit=1)
    start_token = parts[0].strip() if parts else ''
    end_token = parts[1].strip() if len(parts) > 1 else ''
    start = _parse_date_token(start_token) if start_token else None
    end = _parse_date_token(end_token) if end_token else None
    if start is None and end is None:
        return None
    is_current = (end == 'Present') or (not end_token and not end)
    return {"start": start, "end": None if is_current else end,
            "is_current": is_current, "raw": raw}


def _normalize_entry_dates(entry):
    if isinstance(entry, list):
        return [_normalize_entry_dates(e) for e in entry]
    if not isinstance(entry, dict):
        return entry
    result = {}
    for k, v in entry.items():
        if k == 'date' and isinstance(v, str):
            normalized = normalize_date_string(v)
            result[k] = v
            if normalized:
                result['_date_parsed'] = normalized
        else:
            result[k] = _normalize_entry_dates(v)
    return result


def normalize_dates(parsed):
    if not isinstance(parsed, dict):
        return parsed
    result = {}
    for k, v in parsed.items():
        if isinstance(v, list):
            result[k] = _normalize_entry_dates(v)
        elif isinstance(v, dict) and k not in ('contact', '_section_headings'):
            result[k] = _normalize_entry_dates(v)
        else:
            result[k] = v
    return result
