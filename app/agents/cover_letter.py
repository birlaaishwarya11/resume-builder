"""
Cover Letter Agent -- generates tailored cover letters that go beyond the resume.

Architecture:
    1. CONTEXT GATHER  -- read candidate DB, current resume YAML, JD
    2. STORY EXTRACTOR -- identify beyond-resume narratives
    3. GENERATOR       -- LLM produces the letter
    4. REVIEW          -- check format (3-5 paragraphs, 1 page, professional tone)
"""

import os
import json as _json

from app.models import get_user_dir

_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(os.path.dirname(_DIR))  # project root


def _get_database_path(user_id):
    user_path = os.path.join(get_user_dir(user_id), 'candidate_database.md')
    if os.path.exists(user_path):
        return user_path
    return os.path.join(_PROJECT_DIR, 'data', 'defaults', 'candidate_database.md')


def _get_cl_database_path(user_id):
    user_path = os.path.join(get_user_dir(user_id), 'cover_letter_database.md')
    if os.path.exists(user_path):
        return user_path
    return os.path.join(_PROJECT_DIR, 'data', 'defaults', 'cover_letter_database.md')


def _get_story_bank_path(user_id):
    return os.path.join(get_user_dir(user_id), 'cover_letter_stories.json')


def _load_story_bank(user_id):
    path = _get_story_bank_path(user_id)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        if isinstance(data, list):
            return data
    return []


def _read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# Story selection
# ---------------------------------------------------------------------------

def select_stories(jd_text, company_name, user_id, max_stories=4):
    """Select the most relevant beyond-resume stories for a given JD."""
    story_bank = _load_story_bank(user_id)
    if not story_bank:
        return []

    jd_lower = jd_text.lower()

    theme_keywords = {
        "fintech": ["fintech", "financial", "banking", "insurance", "payments"],
        "product-thinking": ["product", "business needs", "stakeholder", "customer"],
        "cross-functional": ["cross-functional", "collaborate", "product manager", "design"],
        "leadership": ["lead", "senior", "mentor", "team", "champion"],
        "ownership": ["ownership", "autonomy", "end-to-end", "full-stack"],
        "engineering-culture": ["code review", "clean", "maintainable", "best practices"],
        "compliance": ["compliance", "regulated", "security", "governance"],
        "infrastructure": ["infrastructure", "cloud", "aws", "kubernetes", "serverless"],
        "reliability": ["reliability", "sre", "incident", "monitoring", "uptime"],
        "ai": ["ai", "machine learning", "ml", "llm", "generative"],
        "safety": ["safety", "trust", "responsible"],
        "impact": ["impact", "mission", "social"],
        "growth": ["growth", "learning", "career"],
        "startup": ["startup", "early-stage", "fast-paced", "series"],
        "healthcare": ["health", "medical", "clinical"],
    }

    scored = []
    for story in story_bank:
        score = 0
        for theme in story.get("theme", []):
            keywords = theme_keywords.get(theme, [theme])
            for kw in keywords:
                if kw in jd_lower:
                    score += 2
                    break
        scored.append((score, story))

    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:max_stories] if s[0] > 0]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

COVER_LETTER_SYSTEM = """\
You are an expert cover letter writer following the Cornell Tech Career Management
Cover Letter Guide. You write letters that go BEYOND the resume, telling the
candidate's story in a way that bullet points cannot.

TONE AND VOICE:
- Write like a real person, not a template. Short sentences mixed with longer ones.
- Subtle excitement through specificity, not adjectives.
- Personal but professional. First person is fine. Contractions are fine.
- Trim ruthlessly. Every sentence should earn its place.
- No corporate cliches.
- No throat-clearing openings.

STRUCTURE:
1. 4 short paragraphs, 1 page max. Shorter is better.
2. Paragraph 1: Quick hook. Role + company + why it caught your eye.
3. Paragraph 2: One story that shows a skill the JD cares about.
4. Paragraph 3: Another story or why THIS company specifically.
5. Paragraph 4: Close. Availability, one sentence. End warm but brief.

RULES:
- Do NOT restate resume bullets.
- Use the Cover Letter Database for stories and career context.
- Use keywords from the JD naturally, never forced.
- Never fabricate experiences or metrics.
- Never use em dashes; use commas, colons, semicolons.
- Never mention visa status or work authorization.
- Address: "Dear Hiring Manager," (unless a contact name is provided)

OUTPUT: The cover letter text only. No headers, no metadata, no commentary.
"""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_cover_letter_prompt(user_id, jd_text, company_name,
                              role_title="", hiring_manager=""):
    """Build the full context for cover letter generation.

    Returns dict with 'system', 'user', 'stories_selected'.
    """
    database = _read_file(_get_database_path(user_id))

    cl_database = ""
    cl_path = _get_cl_database_path(user_id)
    if os.path.exists(cl_path):
        cl_database = _read_file(cl_path)

    resume_path = os.path.join(get_user_dir(user_id), 'resume.yaml')
    resume_yaml = ""
    if os.path.exists(resume_path):
        resume_yaml = _read_file(resume_path)

    stories = select_stories(jd_text, company_name, user_id)
    story_text = "\n\n".join(
        f"STORY: {s['id']}\nThemes: {', '.join(s['theme'])}\n{s['narrative']}"
        for s in stories
    )

    system = COVER_LETTER_SYSTEM

    rules_path = os.path.join(get_user_dir(user_id), 'cover_letter_rules.md')
    if os.path.exists(rules_path):
        user_rules = _read_file(rules_path).strip()
        if user_rules:
            system += f"\n\nADDITIONAL USER RULES:\n{user_rules}"

    if hiring_manager:
        system += f"\n\nAddress the letter to: Dear {hiring_manager},"

    user_parts = [
        f"CANDIDATE DATABASE:\n{database}",
        f"COVER LETTER DATABASE:\n{cl_database}",
        f"CURRENT RESUME (do NOT repeat these bullets):\n{resume_yaml}",
        f"JOB DESCRIPTION:\n{jd_text}",
        f"COMPANY: {company_name}",
    ]
    if role_title:
        user_parts.append(f"ROLE TITLE: {role_title}")
    if story_text:
        user_parts.append(f"BEYOND-RESUME STORIES:\n{story_text}")

    return {
        "system": system,
        "user": "\n\n".join(user_parts),
        "stories_selected": [s["id"] for s in stories],
    }


# ---------------------------------------------------------------------------
# Full generation
# ---------------------------------------------------------------------------

def generate_cover_letter(user_id, jd_text, company_name, provider, api_key,
                          role_title="", hiring_manager="", model=None):
    """Generate a tailored cover letter using an LLM API.

    Returns dict with keys: text, stories_used, company, role
    """
    from app.services.ai import call_llm

    prompt = build_cover_letter_prompt(
        user_id, jd_text, company_name, role_title, hiring_manager
    )
    raw = call_llm(provider, api_key, prompt["system"], prompt["user"], model)

    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()

    output_dir = get_user_dir(user_id)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'cover_letter.txt')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)

    return {
        "text": text,
        "stories_used": prompt["stories_selected"],
        "company": company_name,
        "role": role_title,
        "output_path": output_path,
    }
