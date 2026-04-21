"""
JD Resume Agent -- multi-agent pipeline for generating tailored resumes.

Architecture:
    1. PRE-SCREEN     -- local analysis: blockers, role type, tech keywords
    2. VERSION MATCH  -- check tagged versions for similar JD patterns; reuse as base
    3. GENERATOR      -- LLM creates tailored YAML from candidate DB + rules + JD
    4. PDF FIT        -- render PDF, count pages; if >1 page, compress via abbreviations
    5. ATS VERIFIER   -- separate LLM scores resume against JD (0-100)
    6. LOOP           -- repeat (generator tweak -> pdf fit -> ats verify) until
                         score >= 90 AND pages == 1, or max iterations reached
    7. TAG & SAVE     -- auto-tag version with JD keywords for future reuse
"""

import json
import os
import re
import yaml

from app.services.ai import call_llm, parse_json_response
from app.services.resume import save_current_resume, get_current_resume, tag_version
from app.models import (
    get_user_settings, get_user_dir, DATA_DIR,
    list_resume_versions, get_resume_version, DEFAULT_SECTION_NAMES,
)

_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(os.path.dirname(_DIR))  # project root
_TEMPLATE_DIR = os.path.join(_PROJECT_DIR, 'templates')

DEFAULT_STYLE = {
    'font_family': '"Times New Roman", Times, serif',
    'font_size': '10pt',
    'line_height': '1.15',
    'margin': '0.4in',
    'accent_color': '#000000',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_database_path(user_id):
    user_path = os.path.join(get_user_dir(user_id), 'candidate_database.md')
    if os.path.exists(user_path):
        return user_path
    return os.path.join(_PROJECT_DIR, 'data', 'defaults', 'candidate_database.md')


def _get_rules_path(user_id):
    user_path = os.path.join(get_user_dir(user_id), 'resume_rules.md')
    if os.path.exists(user_path):
        return user_path
    return os.path.join(_PROJECT_DIR, 'data', 'defaults', 'resume_rules.md')


def _read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _strip_yaml_fences(text):
    text = text.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == '```' else len(lines)
        text = '\n'.join(lines[start:end])
    return text.strip()


def _extract_yaml_and_assessment(raw):
    for pattern in [
        r'\n(###?\s*(?:Honest\s+Assessment|Experience\s+Gaps|Assessment))',
        r'\n(##?\s*(?:Honest\s+Assessment|Experience\s+Gaps|Assessment))',
    ]:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            return _strip_yaml_fences(raw[:match.start()].strip()), raw[match.start():].strip()
    return _strip_yaml_fences(raw), ''


def _validate_yaml(content):
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise ValueError('YAML did not parse to a dict')
        return data
    except yaml.YAMLError as e:
        raise ValueError(f'Invalid YAML: {e}') from e


def _md_bold(text):
    if not text:
        return text
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', str(text))


# ---------------------------------------------------------------------------
# PDF rendering and page counting
# ---------------------------------------------------------------------------

def render_pdf(yaml_content, user_id, style=None):
    """Render resume YAML to PDF. Returns the path to the generated PDF."""
    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    style = style or DEFAULT_STYLE.copy()
    resume_data = yaml.safe_load(yaml_content) or {}

    settings = get_user_settings(user_id) if user_id else {}
    section_names = settings.get('section_names', DEFAULT_SECTION_NAMES.copy()) if settings else {}
    custom_sections = settings.get('custom_sections', []) if settings else []

    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))
    env.filters['md_bold'] = _md_bold
    template = env.get_template('resume.html')
    html_content = template.render(
        resume=resume_data, style=style,
        section_names=section_names, custom_sections=custom_sections,
    )

    user_dir = get_user_dir(user_id)
    os.makedirs(user_dir, exist_ok=True)
    pdf_path = os.path.join(user_dir, 'preview.pdf')
    HTML(string=html_content, base_url=_DIR).write_pdf(pdf_path)
    return pdf_path


def count_pdf_pages(pdf_path):
    with open(pdf_path, 'rb') as f:
        content = f.read()
    count = content.count(b'/Type /Page')
    pages_refs = content.count(b'/Type /Pages')
    return max(count - pages_refs, 1)


# ---------------------------------------------------------------------------
# Agent 1: Pre-screener (local, no LLM)
# ---------------------------------------------------------------------------

def analyze_jd(jd_text):
    """Quick local analysis of a JD. Returns role type, blockers, tech keywords."""
    jd_lower = jd_text.lower()

    blockers = []
    blocker_patterns = {
        'Security clearance required': [
            'security clearance', 'clearance required', 'ts/sci',
            'secret clearance', 'top secret',
        ],
        'Visa sponsorship not available': [
            'no sponsorship', 'not sponsor', 'without sponsorship',
            'unable to sponsor', 'will not sponsor', 'cannot sponsor',
            'sponsorship is not available', 'not able to sponsor',
        ],
        'U.S. citizenship required': ['u.s. citizen', 'us citizen'],
    }
    for msg, phrases in blocker_patterns.items():
        if any(p in jd_lower for p in phrases):
            blockers.append(msg)

    role_type = 'general'
    role_signals = {
        'devops': ['devops', 'site reliability', 'sre', 'platform engineer', 'infrastructure engineer'],
        'backend': ['backend', 'back-end', 'server-side', 'api engineer'],
        'ml': ['machine learning', 'ml engineer', 'data scientist', 'deep learning', 'ai/ml'],
        'ai': ['ai engineer', 'llm', 'generative ai', 'agentic', 'ai safety'],
        'fullstack': ['full-stack', 'fullstack', 'full stack'],
        'data': ['data engineer', 'etl', 'data pipeline', 'data platform'],
        'security': ['security engineer', 'appsec', 'devsecops', 'cloud security'],
    }
    for rtype, signals in role_signals.items():
        if any(s in jd_lower for s in signals):
            role_type = rtype
            break

    tech_keywords = [
        'python', 'java', 'typescript', 'javascript', 'go', 'golang', 'rust',
        'c++', 'c#', 'ruby', 'kotlin', 'swift', 'scala',
        'kubernetes', 'docker', 'terraform', 'helm', 'ansible',
        'aws', 'azure', 'gcp', 'google cloud',
        'react', 'next.js', 'node.js', 'fastapi', 'flask', 'django', 'spring boot',
        'postgresql', 'mongodb', 'redis', 'mysql', 'dynamodb', 'cassandra',
        'kafka', 'rabbitmq', 'elasticsearch',
        'prometheus', 'grafana', 'datadog', 'splunk',
        'jenkins', 'github actions', 'gitlab ci', 'circleci',
        'pytorch', 'tensorflow', 'scikit-learn', 'langchain', 'langgraph',
        'openai', 'claude', 'llm', 'rag', 'vector database',
        'ci/cd', 'microservices', 'rest api', 'graphql', 'grpc',
        'agile', 'scrum', 'tdd',
    ]
    found_tech = [t for t in tech_keywords if t in jd_lower]

    return {
        'role_type': role_type,
        'blockers': blockers,
        'detected_technologies': found_tech,
        'has_blockers': len(blockers) > 0,
    }


# ---------------------------------------------------------------------------
# Agent 2: Version matcher
# ---------------------------------------------------------------------------

def find_reusable_version(user_id, jd_text, role_type):
    """Find a previously tagged version whose tags match this JD.

    Returns (yaml_content, version_meta) or (None, None).
    """
    jd_tags = set(extract_jd_tags(jd_text, role_type))
    versions = list_resume_versions(user_id)
    best = None
    best_overlap = 0

    for v in versions:
        tags_raw = v.get('tags')
        if not tags_raw:
            continue
        v_tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
        if not v_tags:
            continue
        v_tag_set = set(t.lower() for t in v_tags)
        overlap = len(jd_tags & v_tag_set)
        if overlap > best_overlap:
            best_overlap = overlap
            best = dict(v, _matched_tags=overlap, _total_tags=len(v_tags))

    if best and best_overlap >= 1:
        full = get_resume_version(best['id'], user_id)
        if full:
            return full['yaml_content'], best

    return None, None


def extract_jd_tags(jd_text, role_type):
    """Extract theme-based tags from a JD. Returns 2-5 lowercase theme tags."""
    jd_lower = jd_text.lower()
    tags = []

    role_themes = {
        'backend': ['backend', 'back-end', 'server-side', 'api engineer', 'api development'],
        'devops': ['devops', 'site reliability', 'sre', 'platform engineer', 'infrastructure engineer'],
        'infra': ['infrastructure', 'cloud engineer', 'cloud platform', 'systems engineer'],
        'fullstack': ['full-stack', 'fullstack', 'full stack'],
        'ai-engineer': ['ai engineer', 'llm engineer', 'generative ai', 'agentic', 'ai platform'],
        'ai-safety': ['ai safety', 'ai governance', 'red team', 'trust and safety', 'responsible ai'],
        'ml': ['machine learning', 'ml engineer', 'deep learning', 'data scientist', 'ml ops', 'mlops'],
        'data': ['data engineer', 'data pipeline', 'etl', 'data platform', 'data infrastructure'],
        'security': ['security engineer', 'appsec', 'devsecops', 'cloud security', 'cybersecurity'],
        'frontend': ['frontend', 'front-end', 'ui engineer', 'react engineer'],
    }
    for theme, signals in role_themes.items():
        if any(s in jd_lower for s in signals):
            tags.append(theme)

    if not tags and role_type != 'general':
        tags.append(role_type)

    domain_themes = {
        'fintech': ['fintech', 'financial', 'banking', 'payments', 'trading', 'capital markets'],
        'healthcare': ['healthcare', 'health tech', 'medical', 'clinical', 'hipaa', 'biotech'],
        'enterprise': ['enterprise', 'b2b', 'saas platform', 'multi-tenant'],
        'startup': ['startup', 'early-stage', 'series a', 'series b', 'seed stage'],
        'observability': ['observability', 'monitoring', 'reliability', 'incident', 'on-call'],
        'data-platform': ['data mesh', 'data catalog', 'data governance', 'data product'],
        'developer-tools': ['developer tools', 'developer experience', 'dx', 'internal tools'],
        'cloud-native': ['cloud-native', 'cloud native', 'containerized', 'serverless'],
    }
    for theme, signals in domain_themes.items():
        if any(s in jd_lower for s in signals) and theme not in tags:
            tags.append(theme)

    return tags[:5] if tags else ['general']


# ---------------------------------------------------------------------------
# Agent 3: Generator (LLM)
# ---------------------------------------------------------------------------

_GENERATE_SYSTEM_TEMPLATE = """\
You are an expert resume writer and ATS optimization specialist.

You will receive:
1. A CANDIDATE DATABASE with all real experience, projects, skills, and metrics
2. RESUME GENERATION RULES with formatting and content guidelines
3. A JOB DESCRIPTION to tailor the resume for
4. Optionally, a BASE RESUME (previously generated for a similar role) to refine

CRITICAL OUTPUT RULES:
- Output ONLY valid YAML first, then assessment after "### Honest Assessment:" heading
- NEVER use em dashes (use commas, colons, semicolons, parentheticals)
- NEVER fabricate skills, technologies, or metrics not in the candidate database

YAML STRUCTURE (follow exactly):
```yaml
{yaml_template}
```

WRITING STYLE (first pass, natural language):
- Write bullets in full, natural English. Do NOT abbreviate words
- Keep bullets to 1-2 lines max
- Use numerals always (3, not "three")
- Combine tool chains inline: "GitLab CI/CD, Terraform, Helm"
- No trailing periods on bullets
- Max 4-5 skill categories, combine related ones
- Prefer concise phrasing but do NOT sacrifice readability for density

After YAML, include:
### Honest Assessment:
What You Actually Have: [list matches]
Experience Gaps: [missing skills]
Blockers: [ONLY hard blockers: visa sponsorship denial, US citizenship required, security clearance]
"""

_ATS_SYSTEM = """\
You are a strict ATS (Applicant Tracking System) scoring engine.
You are a SEPARATE agent verifying another agent's work. Be critical and thorough.

Score the resume YAML against the job description. Return ONLY valid JSON:
{
  "score": <integer 0-100>,
  "matched_keywords": ["keyword1", "keyword2"],
  "missing_keywords": ["keyword1", "keyword2"],
  "section_scores": {
    "skills_match": <0-100>,
    "experience_relevance": <0-100>,
    "keyword_density": <0-100>,
    "quantification": <0-100>
  },
  "suggestions": ["specific actionable improvement 1", "..."]
}

Scoring criteria (be strict):
- Keyword match: exact JD terms present in resume (40% weight)
- Skills alignment: required vs present skills (25% weight)
- Experience relevance: responsibilities match JD duties (20% weight)
- Quantified achievements present and relevant (15% weight)

Rules:
- Only count keywords that GENUINELY appear in the resume text
- Missing a required skill costs 5-10 points
- Generic phrasing without JD keywords costs 3-5 points per instance
- Return ONLY JSON, no markdown, no prose
"""

_COMPRESS_SYSTEM = """\
You are a resume density optimizer. The resume YAML renders to MORE THAN 1 PAGE.
Reduce its length to fit exactly 1 page while preserving important content.

COMPRESSION STRATEGIES (apply in order):
1. Use abbreviations: env, infra, config, auth, dev, ops, prod, k8s, DB, ML, CI/CD, RBAC, IaC, impl, perf, mgmt
2. Drop articles (a, an, the) where meaning stays clear
3. Combine related bullets using semicolons
4. Shorten verbose phrases: "designed and implemented" -> "Built"
5. Remove the least relevant bullets (lowest JD match)
6. Reduce project bullets from 5 to 3 per project
7. Combine skill categories if too many (max 4-5)
8. Trim extracurricular to 1-2 bullets
9. Remove summary if still too long (last resort)
10. Remove extracurricular entirely (last resort)

RULES:
- Never remove entire experience entries
- Never fabricate content
- Never use em dashes
- Keep ** bold markers on action phrases
- Return ONLY valid YAML, no fences, no prose
"""

_IMPROVE_SYSTEM = """\
You are an expert resume editor. You will receive:
1. A resume YAML
2. ATS scoring feedback with missing keywords and suggestions
3. The candidate database (source of truth)
4. The job description

Apply the ATS feedback to improve the resume while keeping it COMPACT (1-page fit).

Rules:
- Only add skills/keywords from the candidate database
- Never fabricate experience or metrics
- Never use em dashes
- Integrate missing keywords into existing bullets or skill lists (don't add new bullets)
- Use abbreviations to save space
- Bold action phrases with ** markers
- Return ONLY the improved YAML (no assessment, no fences, no prose).
"""


def _build_yaml_template(user_id):
    settings = get_user_settings(user_id)
    header = settings.get('header', {})
    name = header.get('name', '[Your Name]')
    contact = header.get('contact', {})

    existing_yaml = get_current_resume(user_id)
    if existing_yaml:
        try:
            existing = yaml.safe_load(existing_yaml) or {}
        except Exception:
            existing = {}
    else:
        existing = {}

    contact_block = {
        'location': contact.get('location', '[City, State]'),
        'phone': contact.get('phone', '[Phone]'),
        'email': contact.get('email', '[email]'),
        'github': contact.get('github', ''),
        'linkedin': contact.get('linkedin', ''),
        'portfolio_label': contact.get('portfolio_label', 'Portfolio'),
        'portfolio_url': contact.get('portfolio_url', ''),
    }
    contact_block = {k: v for k, v in contact_block.items() if v}

    template = {
        'name': name,
        'contact': contact_block,
        'summary': '[2-3 line tailored summary, no em dashes]',
    }

    if existing.get('education'):
        edu_template = []
        for edu in existing['education']:
            edu_template.append({
                'institution': edu.get('institution', '[Institution]'),
                'location': edu.get('location', '[Location]'),
                'degree': edu.get('degree', '[Degree]'),
                'gpa': edu.get('gpa', ''),
                'date': edu.get('date', '[Date]'),
                'coursework': '[relevant courses]',
            })
        template['education'] = edu_template
    else:
        template['education'] = [{'institution': '[Institution]', 'location': '[Location]',
                                   'degree': '[Degree]', 'gpa': '', 'date': '[Date]',
                                   'coursework': '[relevant courses]'}]

    template['technical_skills'] = [{'category': '[JD-relevant name]',
                                      'skills': '[comma-separated, JD keywords first]'}]

    if existing.get('experience'):
        exp_template = []
        for exp in existing['experience']:
            exp_template.append({
                'company': exp.get('company', '[Company]'),
                'role': exp.get('role', '[Role]'),
                'location': exp.get('location', '[Location]'),
                'date': exp.get('date', '[Date]'),
                'bullets': ['[JD-relevant bullets, bold action phrase with **]'],
            })
        template['experience'] = exp_template
    else:
        template['experience'] = [{'company': '[Company]', 'role': '[Role]',
                                    'location': '[Location]', 'date': '[Date]',
                                    'bullets': ['[JD-relevant bullets]']}]

    template['projects'] = [{'name': '[Name (Descriptor)]', 'event': '[Context]',
                              'award': '[If applicable]', 'date': '[Date]',
                              'link_url': '[URL if available]', 'link_text': '[demo or devpost]',
                              'bullets': ['[3-5 bullets per project, 3-4 projects total]']}]
    template['extracurricular'] = {'bullets': ['[2-3 bullets]']}

    return yaml.dump(template, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _get_generate_system(user_id):
    yaml_template = _build_yaml_template(user_id)
    return _GENERATE_SYSTEM_TEMPLATE.format(yaml_template=yaml_template)


# ---------------------------------------------------------------------------
# Agent 3: Generator
# ---------------------------------------------------------------------------

def _generate_resume(user_id, jd_text, provider, api_key, model, base_yaml=None):
    database = _read_file(_get_database_path(user_id))
    rules = _read_file(_get_rules_path(user_id))
    learnings = get_learnings(user_id)

    parts = [
        f"CANDIDATE DATABASE:\n{database}",
        f"RESUME GENERATION RULES:\n{rules}",
        f"JOB DESCRIPTION:\n{jd_text}",
    ]
    if learnings:
        parts.append(f"LEARNINGS FROM PAST USER EDITS:\n{learnings}")
    if base_yaml:
        parts.append(f"BASE RESUME (from a similar role, refine for this JD):\n{base_yaml}")

    user_msg = '\n\n'.join(parts)
    raw = call_llm(provider, api_key, _get_generate_system(user_id), user_msg, model)
    yaml_content, assessment = _extract_yaml_and_assessment(raw)
    _validate_yaml(yaml_content)
    return yaml_content, assessment


# ---------------------------------------------------------------------------
# Agent 4: PDF Fitness checker
# ---------------------------------------------------------------------------

def _check_and_fit_pdf(yaml_content, user_id, jd_text, provider, api_key,
                       model, style=None, max_compress_rounds=2):
    style = style or DEFAULT_STYLE.copy()
    for attempt in range(max_compress_rounds + 1):
        pdf_path = render_pdf(yaml_content, user_id, style)
        pages = count_pdf_pages(pdf_path)
        if pages <= 1:
            return yaml_content, pages
        user_msg = (
            f"CURRENT RESUME YAML ({pages} pages, needs to be 1 page):\n{yaml_content}\n\n"
            f"JOB DESCRIPTION (for relevance-based trimming):\n{jd_text[:3000]}"
        )
        raw = call_llm(provider, api_key, _COMPRESS_SYSTEM, user_msg, model)
        compressed = _strip_yaml_fences(raw)
        try:
            _validate_yaml(compressed)
            yaml_content = compressed
        except ValueError:
            break
    pdf_path = render_pdf(yaml_content, user_id, style)
    pages = count_pdf_pages(pdf_path)
    return yaml_content, pages


# ---------------------------------------------------------------------------
# Agent 5: ATS Verifier
# ---------------------------------------------------------------------------

def score_resume_ats(yaml_content, jd_text, provider, api_key, model=None):
    user_msg = f"RESUME (YAML):\n{yaml_content}\n\nJOB DESCRIPTION:\n{jd_text}"
    raw = call_llm(provider, api_key, _ATS_SYSTEM, user_msg, model)
    result = parse_json_response(raw)
    if not isinstance(result, dict):
        return {'score': 0, 'matched_keywords': [], 'missing_keywords': [], 'suggestions': []}
    return result


# ---------------------------------------------------------------------------
# Agent 6: Improver
# ---------------------------------------------------------------------------

def _improve_resume(user_id, yaml_content, ats_result, jd_text, provider, api_key, model):
    database = _read_file(_get_database_path(user_id))
    feedback = json.dumps(ats_result, indent=2)
    user_msg = (
        f"CURRENT RESUME (YAML):\n{yaml_content}\n\n"
        f"ATS SCORING FEEDBACK:\n{feedback}\n\n"
        f"CANDIDATE DATABASE:\n{database}\n\n"
        f"JOB DESCRIPTION:\n{jd_text}"
    )
    raw = call_llm(provider, api_key, _IMPROVE_SYSTEM, user_msg, model)
    improved = _strip_yaml_fences(raw)
    try:
        _validate_yaml(improved)
        return improved
    except ValueError:
        return yaml_content


# ---------------------------------------------------------------------------
# Orchestrator: the main pipeline
# ---------------------------------------------------------------------------

def generate_resume_for_jd(user_id, jd_text, provider, api_key, model=None,
                           target_score=90, max_iterations=3, style=None):
    """Full multi-agent pipeline: generate, fit, verify, iterate, tag, save.

    Returns dict with keys: yaml, version_id, ats_score, ats_details, assessment,
    pages, role_type, blockers, tags, iterations, logs
    """
    style = style or DEFAULT_STYLE.copy()
    logs = []

    # Phase 1: Pre-screen
    analysis = analyze_jd(jd_text)
    role_type = analysis['role_type']
    logs.append(f"Role type: {role_type}")
    if analysis['has_blockers']:
        logs.append(f"BLOCKERS: {analysis['blockers']}")
    logs.append(f"Detected tech: {', '.join(analysis['detected_technologies'])}")

    # Phase 2: Check for reusable version
    base_yaml, base_meta = find_reusable_version(user_id, jd_text, role_type)
    if base_yaml:
        label = base_meta.get('label', f"v{base_meta['id']}")
        matched = base_meta.get('_matched_tags', '?')
        total = base_meta.get('_total_tags', '?')
        logs.append(f"Reusing version '{label}' ({matched}/{total} tags matched)")
    else:
        logs.append("No matching version found, generating from scratch")

    # Phase 3: Generate initial resume
    logs.append("Generating tailored resume...")
    yaml_content, assessment = _generate_resume(
        user_id, jd_text, provider, api_key, model, base_yaml
    )
    logs.append("Initial YAML generated")

    # Phase 4-6: Fit + Verify loop
    final_ats = {'score': 0}
    iterations_done = 0
    pages = 1

    for i in range(max_iterations):
        iterations_done = i + 1
        yaml_content, pages = _check_and_fit_pdf(
            yaml_content, user_id, jd_text, provider, api_key, model, style
        )
        logs.append(f"Iteration {i + 1}: PDF = {pages} page(s)")

        final_ats = score_resume_ats(yaml_content, jd_text, provider, api_key, model)
        score = final_ats.get('score', 0)
        logs.append(f"Iteration {i + 1}: ATS = {score}/100")

        if score >= target_score and pages <= 1:
            logs.append(f"Target met: ATS {score}/100, {pages} page(s)")
            break

        if score < target_score:
            logs.append(f"Improving: missing {final_ats.get('missing_keywords', [])}")
            yaml_content = _improve_resume(
                user_id, yaml_content, final_ats, jd_text, provider, api_key, model
            )
    else:
        logs.append(f"Max iterations reached ({max_iterations})")

    # Phase 7: Tag and save
    tags = extract_jd_tags(jd_text, role_type)
    version_id = save_current_resume(
        user_id, yaml_content,
        source='jd_agent',
        label=f'JD Agent: {role_type}',
        tags=tags,
    )
    logs.append(f"Saved as version {version_id} with tags: {tags}")
    render_pdf(yaml_content, user_id, style)

    return {
        'yaml': yaml_content,
        'version_id': version_id,
        'ats_score': final_ats.get('score', 0),
        'ats_details': final_ats,
        'assessment': assessment,
        'pages': pages,
        'role_type': role_type,
        'blockers': analysis.get('blockers', []),
        'tags': tags,
        'iterations': iterations_done,
        'logs': logs,
    }


# ---------------------------------------------------------------------------
# Learning system
# ---------------------------------------------------------------------------

def _get_learnings_path(user_id):
    return os.path.join(get_user_dir(user_id), 'resume_learnings.md')


def diff_versions(agent_yaml, user_yaml):
    """Compare agent-generated YAML vs user-edited YAML."""
    agent = yaml.safe_load(agent_yaml) or {}
    user = yaml.safe_load(user_yaml) or {}
    changes = []

    for key in ('summary',):
        av = agent.get(key, '')
        uv = user.get(key, '')
        if str(av).strip() != str(uv).strip():
            changes.append({'section': key, 'type': 'rewritten', 'agent_value': av, 'user_value': uv})

    a_skills = {s.get('category', ''): s.get('skills', '') for s in agent.get('technical_skills', [])}
    u_skills = {s.get('category', ''): s.get('skills', '') for s in user.get('technical_skills', [])}
    if a_skills != u_skills:
        added_cats = set(u_skills) - set(a_skills)
        removed_cats = set(a_skills) - set(u_skills)
        changed_cats = [c for c in set(a_skills) & set(u_skills) if a_skills[c] != u_skills[c]]
        if added_cats or removed_cats or changed_cats:
            changes.append({
                'section': 'technical_skills', 'type': 'modified',
                'added_categories': list(added_cats),
                'removed_categories': list(removed_cats),
                'changed_categories': changed_cats,
            })

    for section_key in ('experience', 'projects'):
        a_items = agent.get(section_key, [])
        u_items = user.get(section_key, [])
        a_names = [_item_name(item) for item in a_items]
        u_names = [_item_name(item) for item in u_items]

        if a_names != u_names:
            changes.append({
                'section': section_key, 'type': 'reordered',
                'agent_order': a_names, 'user_order': u_names,
            })

        a_map = {_item_name(item): item.get('bullets', []) for item in a_items}
        u_map = {_item_name(item): item.get('bullets', []) for item in u_items}

        for name in set(a_map) & set(u_map):
            if a_map[name] != u_map[name]:
                added = [b for b in u_map[name] if b not in a_map[name]]
                removed = [b for b in a_map[name] if b not in u_map[name]]
                if added or removed:
                    changes.append({
                        'section': f'{section_key}/{name}', 'type': 'bullets_changed',
                        'added': added, 'removed': removed,
                    })

    a_proj_names = {_item_name(p) for p in agent.get('projects', [])}
    u_proj_names = {_item_name(p) for p in user.get('projects', [])}
    if a_proj_names != u_proj_names:
        added = u_proj_names - a_proj_names
        removed = a_proj_names - u_proj_names
        if added or removed:
            changes.append({
                'section': 'projects', 'type': 'selection_changed',
                'added': list(added), 'removed': list(removed),
            })

    return changes


def _item_name(item):
    return item.get('company') or item.get('name') or item.get('institution') or '?'


def save_learning(user_id, tags, changes, reason):
    from datetime import datetime
    learnings_path = _get_learnings_path(user_id)
    entry_lines = [
        f"\n## Learning: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Tags:** {', '.join(tags)}",
        f"**Reason:** {reason}",
        "**Changes:**",
    ]
    for c in changes:
        section = c.get('section', '?')
        ctype = c.get('type', '?')
        if ctype == 'bullets_changed':
            added = c.get('added', [])
            removed = c.get('removed', [])
            entry_lines.append(f"- `{section}`: {len(removed)} removed, {len(added)} added")
            for b in added[:3]:
                entry_lines.append(f"  + {b[:120]}")
            for b in removed[:3]:
                entry_lines.append(f"  - {b[:120]}")
        elif ctype == 'reordered':
            entry_lines.append(f"- `{section}`: reordered")
        elif ctype == 'selection_changed':
            if c.get('added'):
                entry_lines.append(f"- `{section}`: added {c['added']}")
            if c.get('removed'):
                entry_lines.append(f"- `{section}`: removed {c['removed']}")
        else:
            entry_lines.append(f"- `{section}`: {ctype}")
    entry_lines.append("")

    entry = '\n'.join(entry_lines)
    if os.path.exists(learnings_path):
        with open(learnings_path, 'a', encoding='utf-8') as f:
            f.write(entry)
    else:
        os.makedirs(os.path.dirname(learnings_path), exist_ok=True)
        with open(learnings_path, 'w', encoding='utf-8') as f:
            f.write("# Resume Generation Learnings\n\n")
            f.write("Patterns learned from user edits to agent-generated resumes.\n")
            f.write(entry)


def get_learnings(user_id):
    learnings_path = _get_learnings_path(user_id)
    if os.path.exists(learnings_path):
        return _read_file(learnings_path)
    return ''


def get_last_agent_version(user_id):
    versions = list_resume_versions(user_id)
    for v in versions:
        if v.get('source') == 'jd_agent':
            full = get_resume_version(v['id'], user_id)
            return full
    return None
