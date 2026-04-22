"""Shared test fixtures.

Unit tests are pure (no DB). Integration tests that hit blueprints need a
live Postgres and skip automatically when DATABASE_URL isn't set.
"""

import os
import secrets

import pytest


def _load_env():
    """Load .env (if present) so local runs don't need `set -a`."""
    env = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if not os.path.exists(env):
        return
    with open(env) as f:
        for raw in f:
            line = raw.rstrip('\n')
            if not line or line.lstrip().startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)


# Load .env at conftest import so any `from app...` at test-module import time
# sees DATABASE_URL before app/config.py snapshots it.
_load_env()


@pytest.fixture(scope='session')
def app():
    if not os.environ.get('DATABASE_URL'):
        pytest.skip('DATABASE_URL not set; skipping integration tests')
    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def signed_up_client(client):
    """Client already authenticated as a fresh throwaway user.

    Yields (client, email, password) so tests can delete the account at the
    end. Keeps the DB clean across runs.
    """
    email = f'pytest-{secrets.token_hex(4)}@example.com'
    password = 'PytestPass123!'
    r = client.post(
        '/signup',
        data={'name': 'Pytest User', 'email': email, 'password': password},
        follow_redirects=True,
    )
    assert r.status_code == 200
    yield client, email, password
    # Best-effort cleanup; ignore failures (test may have deleted already)
    try:
        client.post('/api/delete_profile', json={'password': password})
    except Exception:
        pass
