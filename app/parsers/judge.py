"""
LLM judge: pick or merge the best of two parser outputs.

Used in onboarding when both the heuristic and smart parsers ran successfully
and AI credentials are available. The judge sees the original resume text and
both candidate parses, and returns a single dict in the canonical form schema.

Falls back to a content-count heuristic if the LLM call or its JSON output
is unusable, so the caller never gets `None` when at least one input is valid.
"""

import json
import re

from app.services.ai import call_llm

_RAW_TEXT_BUDGET = 8000
_PARSED_BUDGET = 6000


_CANONICAL_SCHEMA = """\
Top-level keys (omit any that have no data):
  name              str
  contact           {email, phone, location, linkedin, github, portfolio_url, portfolio_label}
  summary           str
  education         list of {institution, degree, location, date, gpa, honors, coursework}
  experience        list of {company, role, location, date, bullets[]}
  technical_skills  list of {category, skills}
  projects          list of {name, subtitle, event, award, date, url, link_url, link_text, bullets[]}
  extracurricular   list of {title, bullets[]}
  _section_headings dict of <key> -> "EXACT HEADING TEXT FROM PDF"

Any section that doesn't fit the canonical names above goes under a top-level
key derived from the heading (lowercased, words joined by underscores), with
each entry shaped as:
  {name, subtitle, date, location, event, award, url, link_url, link_text, bullets[]}\
"""


_JUDGE_PROMPT = """\
You are reviewing two attempts to parse the same resume into structured JSON.
Both attempts target this canonical schema:

{schema}

ORIGINAL RESUME TEXT (truncated for length):
{raw_text}

ATTEMPT A (built-in heuristic parser):
{heuristic_json}

ATTEMPT B (LLM-generated custom parser):
{smart_json}

Return ONE JSON object that uses the canonical schema EXACTLY (no new keys,
no new field names) and represents the best possible parse.

Selection rules:
- For each section, prefer the version that better matches the original text:
  * Correct field assignment (e.g. job title in `role`, city in `location`,
    year only in `date`).
  * Correct entry boundaries (do not over-split or merge entries).
  * Captures more entries from the original text without inventing content.
- If a section is present in only one attempt, include it (mapped into the
  canonical shape if needed).
- Combine bullets so that no bullet present in either attempt is dropped,
  unless it is an exact duplicate.
- For contact, take the longest valid value per field across both attempts.
- Normalise "Present"/"Current"/"Now"/"ongoing" in date strings to "Present".
- Preserve `_section_headings` so original heading text is retained.
- Do NOT hallucinate content that is absent from both attempts.

Respond with ONLY the JSON object - no markdown fences, no explanation.
"""


def judge_and_merge(heuristic_parsed, smart_parsed, raw_text,
                    provider, api_key, model=None):
    """Return the merged best-of-both dict.

    Falls back to whichever input is non-empty (or richer in entry count)
    if the LLM call fails or returns unparseable output.
    """
    if not heuristic_parsed and not smart_parsed:
        return {}
    if not smart_parsed:
        return heuristic_parsed
    if not heuristic_parsed:
        return smart_parsed

    prompt = _JUDGE_PROMPT.format(
        schema=_CANONICAL_SCHEMA,
        raw_text=(raw_text or '')[:_RAW_TEXT_BUDGET],
        heuristic_json=_dump(heuristic_parsed),
        smart_json=_dump(smart_parsed),
    )

    try:
        raw = call_llm(provider, api_key, '', prompt, model)
    except Exception:
        return _pick_richer(heuristic_parsed, smart_parsed)

    parsed = _parse_json_response(raw)
    if not isinstance(parsed, dict) or not parsed:
        return _pick_richer(heuristic_parsed, smart_parsed)
    return parsed


def _dump(obj):
    text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    if len(text) > _PARSED_BUDGET:
        text = text[:_PARSED_BUDGET] + '\n... [truncated]'
    return text


def _parse_json_response(raw):
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r'^```(?:json)?\n?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n?```$', '', text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return None
    return None


def _content_score(parsed):
    """Crude completeness count: total entry-with-text count + filled scalars."""
    if not isinstance(parsed, dict):
        return 0
    score = 0
    for key, val in parsed.items():
        if key in ('name', 'contact', '_section_headings'):
            continue
        if isinstance(val, list):
            for entry in val:
                if isinstance(entry, dict) and any(
                    str(v).strip() for v in entry.values() if v
                ):
                    score += 1
                elif isinstance(entry, str) and entry.strip():
                    score += 1
        elif isinstance(val, str) and val.strip():
            score += 1
    return score


def _pick_richer(a, b):
    return a if _content_score(a) >= _content_score(b) else b
