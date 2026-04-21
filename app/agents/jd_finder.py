"""
JD Finder Agent -- searches for a job posting by company + role,
extracts the JD text, and feeds it into the resume generation pipeline.
"""

import json

from app.services.ai import call_llm, parse_json_response
from app.agents.jd_resume import generate_resume_for_jd, analyze_jd


_JOB_BOARDS = [
    'greenhouse.io', 'lever.co', 'ashbyhq.com', 'jobs.lever.co',
    'boards.greenhouse.io', 'apply.workable.com', 'careers.smartrecruiters.com',
    'myworkdayjobs.com', 'icims.com', 'jobvite.com',
    'linkedin.com/jobs', 'indeed.com', 'wellfound.com',
]


def build_search_query(company, role):
    """Build the best single search query for finding a JD."""
    return f"{company} {role} job posting 2026"


_EXTRACT_SYSTEM = """\
You are a job description extractor. Given the raw content of a job posting page,
extract ONLY the job description text. Include:
- Job title, company name, location and work arrangement
- About the role / overview
- Responsibilities / What you'll do
- Requirements / Qualifications
- Tech stack / Tools mentioned
- Compensation (if listed)
- Visa/sponsorship info (if mentioned)

Do NOT include navigation menus, footers, cookie notices, or other job listings.
Return the extracted JD as clean text. If no JD found, respond: NO_JD_FOUND
"""


def extract_jd_from_html(page_content, provider, api_key, model=None):
    """Extract structured JD text from raw page content using an LLM."""
    content = page_content[:15000]
    raw = call_llm(provider, api_key, _EXTRACT_SYSTEM, content, model)
    if 'NO_JD_FOUND' in raw:
        return None
    return raw.strip()


_SELECT_SYSTEM = """\
You are a job posting URL selector. Given search results for a specific company and role,
identify which URL is most likely the actual job posting.

Prefer URLs from: greenhouse.io, lever.co, ashbyhq.com, workable.com,
myworkdayjobs.com, linkedin.com/jobs, wellfound.com, or the company's careers page.

Return ONLY a JSON object:
{"best_url": "https://...", "confidence": "high"|"medium"|"low", "reason": "why"}

If none found: {"best_url": null, "confidence": "none", "reason": "no job posting found"}
"""


def select_best_url(search_results, company, role, provider, api_key, model=None):
    """Given search result text, pick the best URL for the actual job posting."""
    user_msg = f"Company: {company}\nRole: {role}\n\nSearch Results:\n{search_results}"
    raw = call_llm(provider, api_key, _SELECT_SYSTEM, user_msg, model)
    result = parse_json_response(raw)
    if not isinstance(result, dict):
        return {'best_url': None, 'confidence': 'none', 'reason': 'Failed to parse response'}
    return result


def find_and_generate(user_id, provider, api_key, model=None,
                      company=None, role=None, url=None,
                      jd_text=None, target_score=90):
    """Find a JD and run the full resume generation pipeline.

    Provide EITHER company+role, url, or jd_text directly.
    """
    logs = []
    jd_source = 'direct'
    jd_url = url

    if jd_text:
        jd_source = 'direct'
        logs.append("Using provided JD text directly")
    elif url:
        jd_source = 'url'
        raise ValueError(
            "URL extraction requires page content. Use extract_jd_from_html() "
            "with fetched content, then pass as jd_text."
        )
    elif company and role:
        jd_source = 'search'
        raise ValueError(
            "Search flow requires caller to perform web search. "
            "Use build_search_query(), search, extract, then pass jd_text."
        )
    else:
        raise ValueError("Provide company+role, url, or jd_text")

    analysis = analyze_jd(jd_text)
    logs.append(f"Role type: {analysis['role_type']}")
    if analysis['has_blockers']:
        logs.append(f"BLOCKERS: {analysis['blockers']}")

    result = generate_resume_for_jd(
        user_id=user_id, jd_text=jd_text,
        provider=provider, api_key=api_key,
        model=model, target_score=target_score,
    )

    result['jd_source'] = jd_source
    result['jd_url'] = jd_url
    result['jd_text'] = jd_text
    result['finder_logs'] = logs + result.get('logs', [])

    return result
