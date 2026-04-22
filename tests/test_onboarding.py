"""Integration tests for the onboarding API contract.

These cover the endpoints the new form-based onboarding UI talks to:

    /api/preview               (uses yaml_content key, not resume)
    /api/complete_onboarding   (resume YAML + header + custom_sections + section_names)
    /api/settings              (reads back what was saved)

Skipped automatically when DATABASE_URL is not set; see conftest.py.
"""

import yaml


BASE_BODY = {
    'summary': 'Engineer with 5 years of experience.',
    'experience': [
        {
            'company': 'Acme Corp',
            'role': 'Senior Engineer',
            'location': 'SF',
            'date': 'Jan 2022 - Present',
            'bullets': ['Led a migration.', 'Mentored two juniors.'],
        },
    ],
    'education': [
        {'institution': 'UC Berkeley', 'degree': 'BS CS', 'date': 'May 2020'},
    ],
    'technical_skills': [
        {'category': 'Languages', 'skills': 'Python, Go'},
    ],
}
BASE_HEADER = {
    'name': 'Test User',
    'contact': {
        'email': 'test@example.com',
        'location': 'Remote',
        'phone': '555-0000',
    },
}


def _post_json(client, path, payload):
    return client.post(path, json=payload)


class TestPreviewContract:
    """The new form JS posts to /api/preview with yaml_content (not `resume`)."""

    def test_preview_accepts_yaml_content_key(self, signed_up_client):
        client, _, _ = signed_up_client
        body_yaml = yaml.dump(BASE_BODY, sort_keys=False)
        r = _post_json(client, '/api/preview', {
            'yaml_content': body_yaml,
            'header': BASE_HEADER,
            'section_names': {},
            'custom_sections': [],
            'style': {},
        })
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'Test User' in html
        assert 'Acme Corp' in html

    def test_preview_renders_custom_section_heading(self, signed_up_client):
        client, _, _ = signed_up_client
        body = dict(BASE_BODY)
        body['awards'] = ["Dean's List", 'Best Paper 2023']
        custom = [{'key': 'awards', 'display_name': 'AWARDS', 'render_type': 'bullets'}]
        r = _post_json(client, '/api/preview', {
            'yaml_content': yaml.dump(body, sort_keys=False),
            'header': BASE_HEADER,
            'section_names': {'awards': 'AWARDS'},
            'custom_sections': custom,
            'style': {},
        })
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'AWARDS' in html
        assert "Dean's List" in html

    def test_preview_skips_empty_custom_section(self, signed_up_client):
        """Parsed-but-empty custom sections should not appear as empty blocks."""
        client, _, _ = signed_up_client
        body = dict(BASE_BODY)
        body['publications'] = []
        custom = [{'key': 'publications', 'display_name': 'PUBLICATIONS', 'render_type': 'bullets'}]
        r = _post_json(client, '/api/preview', {
            'yaml_content': yaml.dump(body, sort_keys=False),
            'header': BASE_HEADER,
            'section_names': {'publications': 'PUBLICATIONS'},
            'custom_sections': custom,
            'style': {},
        })
        assert r.status_code == 200
        assert 'PUBLICATIONS' not in r.get_data(as_text=True)


class TestCompleteOnboardingContract:
    """The form submits the final state to /api/complete_onboarding."""

    def test_saves_resume_and_marks_complete(self, signed_up_client):
        client, _, _ = signed_up_client
        r = _post_json(client, '/api/complete_onboarding', {
            'resume': yaml.dump(BASE_BODY, sort_keys=False),
            'header': BASE_HEADER,
            'style': {},
            'custom_sections': [],
            'section_names': {},
        })
        assert r.status_code == 200
        assert r.get_json()['status'] == 'success'
        # After completion, GET / must not redirect to /onboarding
        r = client.get('/', follow_redirects=False)
        loc = r.headers.get('Location', '') or ''
        assert '/onboarding' not in loc

    def test_saves_custom_sections_to_settings(self, signed_up_client):
        client, _, _ = signed_up_client
        custom = [
            {'key': 'awards', 'display_name': 'AWARDS', 'render_type': 'bullets'},
            {'key': 'publications', 'display_name': 'PUBLICATIONS', 'render_type': 'bullets'},
        ]
        section_names = {
            'awards': 'AWARDS & HONORS',
            'publications': 'PUBLICATIONS',
            'experience': 'EXPERIENCE',
        }
        body = dict(BASE_BODY)
        body['awards'] = ['Award one', 'Award two']

        r = _post_json(client, '/api/complete_onboarding', {
            'resume': yaml.dump(body, sort_keys=False),
            'header': BASE_HEADER,
            'style': {},
            'custom_sections': custom,
            'section_names': section_names,
        })
        assert r.status_code == 200

        # /api/settings reads back the saved settings
        r = client.get('/api/settings')
        assert r.status_code == 200
        data = r.get_json()
        saved_keys = [cs['key'] for cs in data.get('custom_sections', [])]
        assert 'awards' in saved_keys
        assert 'publications' in saved_keys
        # Section names persist (with deep merges including defaults)
        assert data['section_names'].get('awards') == 'AWARDS & HONORS'
        assert data['section_names'].get('experience') == 'EXPERIENCE'

    def test_second_call_rejected(self, signed_up_client):
        client, _, _ = signed_up_client
        payload = {
            'resume': yaml.dump(BASE_BODY, sort_keys=False),
            'header': BASE_HEADER,
            'style': {},
            'custom_sections': [],
            'section_names': {},
        }
        first = _post_json(client, '/api/complete_onboarding', payload)
        assert first.status_code == 200
        second = _post_json(client, '/api/complete_onboarding', payload)
        assert second.status_code == 400
        assert 'already' in (second.get_json() or {}).get('message', '').lower()


class TestOnboardingPageRenders:
    """Smoke test: the onboarding template renders without Jinja errors
    and contains the new form-pane (no ace editor)."""

    def test_template_has_form_pane_not_ace(self, signed_up_client):
        client, _, _ = signed_up_client
        r = client.get('/onboarding')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'review-form-pane' in html
        assert 'js-yaml' in html  # library loaded
        assert 'ob-ace-editor' not in html  # old editor removed
