"""Tests for service layer functions."""

import json
import pytest

from app.services.ai import parse_json_response, extract_ai_error
from app.services.resume import parse_yaml, dump_yaml, _validate_yaml
from app.services.jd import _score_version_for_jd, _strip_yaml_fences


# ---------------------------------------------------------------------------
# ai.py
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_clean_json(self):
        result = parse_json_response('{"score": 85, "suggestions": []}')
        assert result == {"score": 85, "suggestions": []}

    def test_json_with_fences(self):
        text = '```json\n{"score": 90}\n```'
        result = parse_json_response(text)
        assert result == {"score": 90}

    def test_json_in_prose(self):
        text = 'Here is the analysis:\n{"score": 75, "suggestions": ["add Python"]}'
        result = parse_json_response(text)
        assert result['score'] == 75

    def test_array_response(self):
        result = parse_json_response('[{"id": "a"}, {"id": "b"}]')
        assert len(result) == 2

    def test_unparseable(self):
        result = parse_json_response('This is not JSON at all')
        assert result == {}


class TestExtractAiError:
    def test_with_status_code(self):
        class FakeExc(Exception):
            status_code = 401
        err = extract_ai_error(FakeExc('Unauthorized'))
        assert err['status_code'] == 401
        assert 'Unauthorized' in err['message']

    def test_without_status_code(self):
        err = extract_ai_error(ValueError('Something broke'))
        assert err['status_code'] is None
        assert 'Something broke' in err['message']


# ---------------------------------------------------------------------------
# resume.py
# ---------------------------------------------------------------------------

class TestResumeHelpers:
    def test_parse_yaml_valid(self):
        result = parse_yaml('name: Alice\nemail: alice@test.com')
        assert result['name'] == 'Alice'

    def test_parse_yaml_empty(self):
        assert parse_yaml('') == {}
        assert parse_yaml(None) == {}

    def test_parse_yaml_non_dict(self):
        assert parse_yaml('- item1\n- item2') == {}

    def test_dump_yaml(self):
        data = {'name': 'Bob', 'skills': ['Python', 'Go']}
        result = dump_yaml(data)
        assert 'name: Bob' in result
        assert 'Python' in result

    def test_validate_yaml_valid(self):
        _validate_yaml('name: Test\nage: 25')

    def test_validate_yaml_invalid(self):
        with pytest.raises(ValueError, match='Invalid YAML'):
            _validate_yaml('name: [invalid yaml')


# ---------------------------------------------------------------------------
# jd.py
# ---------------------------------------------------------------------------

class TestJdHelpers:
    def test_score_version_for_jd_full_match(self):
        tags = ['python', 'backend', 'aws']
        jd = 'We need a Python backend engineer with AWS experience'
        score = _score_version_for_jd(tags, jd)
        assert score == 1.0

    def test_score_version_for_jd_partial(self):
        tags = ['python', 'frontend', 'aws']
        jd = 'We need a Python backend engineer with AWS experience'
        score = _score_version_for_jd(tags, jd)
        assert abs(score - 2/3) < 0.01

    def test_score_version_for_jd_no_match(self):
        tags = ['ruby', 'frontend']
        jd = 'We need a Python backend engineer'
        assert _score_version_for_jd(tags, jd) == 0.0

    def test_score_version_for_jd_empty_tags(self):
        assert _score_version_for_jd([], 'any text') == 0.0

    def test_strip_yaml_fences(self):
        text = '```yaml\nname: Test\n```'
        assert _strip_yaml_fences(text) == 'name: Test'

    def test_strip_yaml_fences_no_fences(self):
        text = 'name: Test'
        assert _strip_yaml_fences(text) == 'name: Test'
