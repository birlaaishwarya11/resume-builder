"""
Cover Letter Agent -- generates tailored cover letters that go beyond the resume.

Architecture:
    1. CONTEXT GATHER  -- read candidate DB, current resume YAML, JD
    2. STORY EXTRACTOR -- identify beyond-resume narratives
    3. GENERATOR       -- LLM produces the letter
    4. REVIEW          -- check format (3-5 paragraphs, 1 page, professional tone)
"""

from app.services import documents
from app.agents.safety import UNTRUSTED_INPUT_NOTICE, fence_untrusted


# ---------------------------------------------------------------------------
# Story selection
# ---------------------------------------------------------------------------

def select_stories(jd_text, company_name, user_id, max_stories=4):
    """Select the most relevant beyond-resume stories for a given JD.

    Story bank is not currently persisted; returns an empty list. Retained as
    an extension point for a future `cover_letter_stories` document field.
    """
    return []


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
    database = documents.get_candidate_database(user_id)
    cl_database = documents.get_cover_letter_database(user_id)
    resume_yaml = documents.get_resume_yaml(user_id)

    stories = select_stories(jd_text, company_name, user_id)
    story_text = "\n\n".join(
        f"STORY: {s['id']}\nThemes: {', '.join(s['theme'])}\n{s['narrative']}"
        for s in stories
    )

    system = COVER_LETTER_SYSTEM + "\n\n" + UNTRUSTED_INPUT_NOTICE

    user_rules = documents.get_cover_letter_rules(user_id).strip()
    if user_rules:
        system += f"\n\nADDITIONAL USER RULES:\n{user_rules}"

    if hiring_manager:
        system += f"\n\nAddress the letter to: Dear {hiring_manager},"

    user_parts = [
        f"CANDIDATE DATABASE:\n{database}",
        f"COVER LETTER DATABASE:\n{cl_database}",
        f"CURRENT RESUME (do NOT repeat these bullets):\n{resume_yaml}",
        fence_untrusted("JOB DESCRIPTION:", jd_text),
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

    return {
        "text": text,
        "stories_used": prompt["stories_selected"],
        "company": company_name,
        "role": role_title,
    }
