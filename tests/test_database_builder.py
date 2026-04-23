"""Unit tests for the database-builder agent (pure-Python pieces only).

LLM and HTTP paths are not exercised here -- they need network/keys and are
covered by manual curl + the existing safety tests.
"""

import pytest

from app.agents.database_builder import (
    BudgetExceeded,
    BuildBudget,
    _normalize_topic_flag,
    consolidate_candidate_db,
    consolidate_cl_db,
    extract_outbound_links,
    is_devpost_url,
    is_github_url,
    parse_github_repo,
)


class TestBuildBudget:
    def test_default_budget_nonzero(self):
        b = BuildBudget()
        u = b.usage()
        assert u['fetches_remaining'] > 0
        assert u['llm_calls_remaining'] > 0
        assert u['bytes_remaining'] > 0

    def test_spend_decrements(self):
        b = BuildBudget(fetches=2, llm_calls=2, bytes_in=100)
        b.spend_fetch()
        b.spend_llm()
        b.spend_bytes(40)
        u = b.usage()
        assert u['fetches_remaining'] == 1
        assert u['llm_calls_remaining'] == 1
        assert u['bytes_remaining'] == 60

    def test_fetch_exhaustion_raises(self):
        b = BuildBudget(fetches=1, llm_calls=10, bytes_in=10)
        b.spend_fetch()
        with pytest.raises(BudgetExceeded):
            b.spend_fetch()

    def test_llm_exhaustion_raises(self):
        b = BuildBudget(fetches=10, llm_calls=1, bytes_in=10)
        b.spend_llm()
        with pytest.raises(BudgetExceeded):
            b.spend_llm()

    def test_bytes_clamp_then_exhaustion(self):
        # Spending more than remaining clamps to 0, no raise. The next spend
        # then raises.
        b = BuildBudget(fetches=10, llm_calls=10, bytes_in=50)
        b.spend_bytes(80)
        assert b.bytes_in == 0
        with pytest.raises(BudgetExceeded):
            b.spend_bytes(1)

    def test_spend_bytes_zero_noop(self):
        b = BuildBudget(fetches=10, llm_calls=10, bytes_in=50)
        b.spend_bytes(0)
        assert b.bytes_in == 50


class TestUrlClassification:
    def test_github_repo_url(self):
        assert is_github_url('https://github.com/owner/repo')
        owner, repo = parse_github_repo('https://github.com/owner/repo')
        assert (owner, repo) == ('owner', 'repo')

    def test_github_repo_with_dot_git(self):
        owner, repo = parse_github_repo('https://github.com/owner/repo.git')
        assert (owner, repo) == ('owner', 'repo')

    def test_github_user_only_not_repo(self):
        assert is_github_url('https://github.com/owner')
        owner, repo = parse_github_repo('https://github.com/owner')
        assert owner is None and repo is None

    def test_github_subpath_not_repo(self):
        # /owner/repo/issues is a subpath, not a top-level repo URL.
        owner, repo = parse_github_repo('https://github.com/owner/repo/issues')
        assert owner is None and repo is None

    def test_non_github(self):
        assert not is_github_url('https://example.com/owner/repo')

    def test_devpost(self):
        assert is_devpost_url('https://devpost.com/software/foo')
        assert is_devpost_url('https://www.devpost.com/foo')
        assert not is_devpost_url('https://example.com/devpost')


class TestExtractOutboundLinks:
    BASE = 'https://portfolio.example.com/'

    def _html(self, *hrefs):
        body = ''.join(f'<a href="{h}">x</a>' for h in hrefs)
        return f'<html><body>{body}</body></html>'

    def test_keeps_same_origin(self):
        html = self._html('/projects/foo', 'https://portfolio.example.com/about')
        out = extract_outbound_links(html, self.BASE)
        assert 'https://portfolio.example.com/projects/foo' in out
        assert 'https://portfolio.example.com/about' in out

    def test_keeps_known_project_domains(self):
        html = self._html(
            'https://github.com/me/repo',
            'https://devpost.com/software/x',
            'https://kaggle.com/me',
        )
        out = extract_outbound_links(html, self.BASE)
        assert 'https://github.com/me/repo' in out
        assert 'https://devpost.com/software/x' in out
        assert 'https://kaggle.com/me' in out

    def test_drops_unknown_domains(self):
        html = self._html('https://random-blog.example.org/post')
        out = extract_outbound_links(html, self.BASE)
        assert out == []

    def test_drops_seed_self(self):
        html = self._html(self.BASE, self.BASE.rstrip('/'))
        out = extract_outbound_links(html, self.BASE)
        assert out == []

    def test_drops_fragments_mailto_javascript(self):
        html = self._html('#about', 'mailto:x@y', 'javascript:alert(1)')
        out = extract_outbound_links(html, self.BASE)
        assert out == []

    def test_drops_noise_paths(self):
        html = self._html(
            'https://portfolio.example.com/login',
            'https://portfolio.example.com/tag/python',
        )
        out = extract_outbound_links(html, self.BASE)
        assert out == []

    def test_dedupes(self):
        html = self._html('/projects/foo', '/projects/foo')
        out = extract_outbound_links(html, self.BASE)
        assert len(out) == 1


class TestConsolidateCandidateDB:
    def test_empty(self):
        md = consolidate_candidate_db([])
        assert 'No items extracted' in md

    def test_groups_and_sorts_by_recency(self):
        items = [
            {'kind': 'project', 'title': 'Old', 'date_year': 2020,
             'summary': 'old summary'},
            {'kind': 'project', 'title': 'New', 'date_year': 2024,
             'summary': 'new summary'},
            {'kind': 'experience', 'title': 'Job', 'date_year': 2023,
             'org': 'Acme', 'role': 'SWE'},
        ]
        md = consolidate_candidate_db(items)
        # Experience section appears before Project section.
        assert md.index('## Experience') < md.index('## Project')
        # Within Project section, New (2024) appears before Old (2020).
        proj_section = md[md.index('## Project'):]
        assert proj_section.index('### New') < proj_section.index('### Old')

    def test_dateless_items_sink_to_bottom_of_section(self):
        items = [
            {'kind': 'project', 'title': 'Dated', 'date_year': 2023},
            {'kind': 'project', 'title': 'Undated'},
        ]
        md = consolidate_candidate_db(items)
        assert md.index('### Dated') < md.index('### Undated')
        assert 'date: unknown' in md

    def test_unknown_kind_buckets_to_other(self):
        items = [{'kind': 'mystery', 'title': 'X'}]
        md = consolidate_candidate_db(items)
        assert '## Other' in md
        assert '### X' in md

    def test_renders_tech_and_source(self):
        items = [{
            'kind': 'project', 'title': 'P',
            'tech': ['python', 'fastapi'],
            'url': 'https://example.com/p',
            'bullets': ['shipped a thing'],
        }]
        md = consolidate_candidate_db(items)
        assert '**Tech:** python, fastapi' in md
        assert 'Source: https://example.com/p' in md
        assert '- shipped a thing' in md


class TestTopicFlagDefaults:
    def test_missing_flag_defaults_true(self):
        rec = {'title': 'X'}
        _normalize_topic_flag(rec)
        assert rec['on_topic'] is True
        assert 'no relevance flag' in rec['topic_reason']

    def test_explicit_false_preserved(self):
        rec = {'title': 'X', 'on_topic': False, 'topic_reason': 'unrelated'}
        _normalize_topic_flag(rec)
        assert rec['on_topic'] is False
        assert rec['topic_reason'] == 'unrelated'

    def test_non_bool_flag_falls_back_to_true(self):
        rec = {'on_topic': 'yes'}
        _normalize_topic_flag(rec)
        assert rec['on_topic'] is True


class TestConsolidateOffTopicFiltering:
    def test_off_topic_items_dropped_by_default(self):
        items = [
            {'kind': 'project', 'title': 'Real', 'on_topic': True},
            {'kind': 'project', 'title': 'Spam', 'on_topic': False},
        ]
        md = consolidate_candidate_db(items)
        assert '### Real' in md
        assert '### Spam' not in md

    def test_off_topic_items_included_when_flag_on(self):
        items = [
            {'kind': 'project', 'title': 'Real', 'on_topic': True},
            {'kind': 'project', 'title': 'Spam', 'on_topic': False},
        ]
        md = consolidate_candidate_db(items, include_off_topic=True)
        assert '### Real' in md
        assert '### Spam' in md

    def test_off_topic_moments_dropped_by_default(self):
        moments = [
            {'kind': 'mission', 'title': 'Real', 'narrative': 'r', 'on_topic': True},
            {'kind': 'story', 'title': 'Spam', 'narrative': 's', 'on_topic': False},
        ]
        md = consolidate_cl_db(moments)
        assert '### Real' in md
        assert '### Spam' not in md

    def test_only_off_topic_yields_empty_message(self):
        items = [{'kind': 'project', 'title': 'Spam', 'on_topic': False}]
        md = consolidate_candidate_db(items)
        assert 'No items extracted' in md


class TestConsolidateCLDB:
    def test_empty(self):
        md = consolidate_cl_db([])
        assert 'No moments extracted' in md

    def test_orders_known_kinds_first(self):
        moments = [
            {'kind': 'passion', 'title': 'P', 'narrative': 'p'},
            {'kind': 'mission', 'title': 'M', 'narrative': 'm'},
            {'kind': 'challenge', 'title': 'C', 'narrative': 'c'},
        ]
        md = consolidate_cl_db(moments)
        assert md.index('## Mission') < md.index('## Challenge') < md.index('## Passion')

    def test_renders_themes_and_source(self):
        moments = [{
            'kind': 'story', 'title': 'T', 'narrative': 'n',
            'themes': ['ownership', 'curiosity'],
            'url': 'https://example.com/x',
        }]
        md = consolidate_cl_db(moments)
        assert '**Themes:** ownership, curiosity' in md
        assert 'Source: https://example.com/x' in md
