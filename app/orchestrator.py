"""
Resume Orchestrator -- central coordinator for agent and service calls.

Blueprints construct an orchestrator instance with resolved credentials,
then call the appropriate method. This replaces the ad-hoc credential
resolution and agent calls scattered across Flask routes.
"""

from app.models import get_user_api_config
from app.services.crypto import decrypt_api_key
import app.agents.jd_resume as jd_resume_agent
import app.agents.cover_letter as cover_letter_agent
import app.agents.jd_finder as jd_finder_agent
import app.services.jd as jd_service


class ResumeOrchestrator:
    """Wraps all agent/service calls with pre-resolved credentials."""

    def __init__(self, user_id: int, provider: str, api_key: str,
                 model: str | None = None):
        self.user_id = user_id
        self.provider = provider
        self.api_key = api_key
        self.model = model

    # --- Resume generation (7-stage agent pipeline) ---

    def generate_for_jd(self, jd_text: str, target_score: int = 90) -> dict:
        """Full pipeline: pre-screen -> version match -> generate -> fit -> verify -> tag."""
        return jd_resume_agent.generate_resume_for_jd(
            self.user_id, jd_text, self.provider, self.api_key,
            self.model, target_score=target_score,
        )

    # --- JD analysis (score + suggestions) ---

    def analyze_jd(self, jd_text: str) -> tuple:
        """Analyze resume against JD. Returns (session_id, results, logs)."""
        return jd_service.analyze(
            self.user_id, jd_text, self.provider, self.api_key, self.model,
        )

    def apply_suggestions(self, session_id: int, suggestion_ids: list) -> tuple:
        """Apply selected suggestions. Returns (new_yaml, version_id, logs)."""
        return jd_service.apply_suggestions(
            self.user_id, session_id, suggestion_ids,
            self.provider, self.api_key, self.model,
        )

    def apply_full_jd(self, jd_text: str, min_priority: int = 2) -> tuple:
        """Analyze and apply all high-priority suggestions."""
        return jd_service.apply_full(
            self.user_id, jd_text, self.provider, self.api_key,
            self.model, min_priority=min_priority,
        )

    # --- Cover letter ---

    def generate_cover_letter(self, jd_text: str, company_name: str,
                              role_title: str = "", hiring_manager: str = "") -> dict:
        return cover_letter_agent.generate_cover_letter(
            self.user_id, jd_text, company_name,
            self.provider, self.api_key,
            role_title=role_title, hiring_manager=hiring_manager,
            model=self.model,
        )

    # --- JD finder ---

    def find_jd(self, company: str = None, role: str = None,
                url: str = None, jd_text: str = None,
                target_score: int = 90) -> dict:
        return jd_finder_agent.find_and_generate(
            self.user_id, self.provider, self.api_key,
            model=self.model, company=company, role=role,
            url=url, jd_text=jd_text, target_score=target_score,
        )

    # --- Quick ATS score (no session, no save) ---

    def quick_ats_score(self, jd_text: str) -> dict:
        """Score current resume against JD without creating a session."""
        from app.services.resume import get_current_resume
        resume_yaml = get_current_resume(self.user_id)
        if not resume_yaml:
            raise ValueError('No resume found')
        return jd_resume_agent.score_resume_ats(
            resume_yaml, jd_text, self.provider, self.api_key, self.model,
        )


def resolve_ai_credentials(request_data: dict, user_id: int) -> tuple:
    """Return (provider, api_key, model) from request body or DB.

    Request body values override DB-stored config.
    Raises ValueError if no API key is available.
    """
    provider = (request_data.get('provider') or
                request_data.get('ai_provider') or '').strip()
    api_key = (request_data.get('api_key') or
               request_data.get('ai_api_key') or '').strip()
    model = (request_data.get('model') or
             request_data.get('ai_model') or '').strip() or None

    if not api_key:
        config = get_user_api_config(user_id)
        if config and config.get('ai_api_key_encrypted'):
            api_key = decrypt_api_key(config['ai_api_key_encrypted'])
            provider = provider or config.get('provider') or 'anthropic'
            model = model or config.get('model')

    if not api_key:
        raise ValueError(
            'No API key configured. Add one in Settings or include it in the request.'
        )
    if not provider:
        provider = 'anthropic'

    return provider, api_key, model


def get_orchestrator(request_data: dict, user_id: int) -> ResumeOrchestrator:
    """Factory: resolve credentials and return an orchestrator instance."""
    provider, api_key, model = resolve_ai_credentials(request_data, user_id)
    return ResumeOrchestrator(user_id, provider, api_key, model)
