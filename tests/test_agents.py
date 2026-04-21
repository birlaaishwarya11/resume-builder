"""Tests for agent functions (local-only, no LLM calls)."""

from app.agents.jd_resume import analyze_jd, extract_jd_tags


class TestAnalyzeJd:
    def test_backend_role(self):
        jd = "We are looking for a backend engineer with Python and PostgreSQL experience."
        result = analyze_jd(jd)
        assert result['role_type'] == 'backend'
        assert not result['has_blockers']
        assert 'python' in result['detected_technologies']
        assert 'postgresql' in result['detected_technologies']

    def test_devops_role(self):
        jd = "SRE / DevOps engineer needed. Kubernetes, Terraform, AWS, CI/CD pipelines."
        result = analyze_jd(jd)
        assert result['role_type'] == 'devops'
        assert 'kubernetes' in result['detected_technologies']
        assert 'terraform' in result['detected_technologies']

    def test_ml_role(self):
        jd = "Machine learning engineer. PyTorch, deep learning, model deployment."
        result = analyze_jd(jd)
        assert result['role_type'] == 'ml'
        assert 'pytorch' in result['detected_technologies']

    def test_blocker_citizenship(self):
        jd = "Backend engineer. Must be a U.S. citizen. Python required."
        result = analyze_jd(jd)
        assert result['has_blockers']
        assert any('citizenship' in b.lower() for b in result['blockers'])

    def test_blocker_sponsorship(self):
        jd = "We will not sponsor visas for this position. Go engineer needed."
        result = analyze_jd(jd)
        assert result['has_blockers']
        assert any('sponsorship' in b.lower() for b in result['blockers'])

    def test_no_blockers(self):
        jd = "Full-stack engineer. React, Node.js, PostgreSQL. Remote friendly."
        result = analyze_jd(jd)
        assert not result['has_blockers']
        assert result['role_type'] == 'fullstack'


class TestExtractJdTags:
    def test_backend_tags(self):
        tags = extract_jd_tags("Backend engineer at a fintech startup", "backend")
        assert 'backend' in tags
        assert 'fintech' in tags

    def test_devops_tags(self):
        tags = extract_jd_tags("Platform engineer for cloud-native infrastructure", "devops")
        assert 'devops' in tags or 'infra' in tags
        assert 'cloud-native' in tags

    def test_general_fallback(self):
        tags = extract_jd_tags("We need someone great", "general")
        assert tags == ['general']

    def test_max_5_tags(self):
        jd = ("AI engineer at a healthcare fintech startup building cloud-native "
              "developer tools with observability")
        tags = extract_jd_tags(jd, "ai")
        assert len(tags) <= 5
