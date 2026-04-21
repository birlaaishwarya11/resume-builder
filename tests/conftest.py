"""Shared test fixtures."""

import os
import tempfile

import pytest


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        defaults_dir = os.path.join(tmpdir, 'defaults')
        os.makedirs(defaults_dir)
        # Create minimal default files
        for fname in ('candidate_database.md', 'resume_rules.md',
                      'cover_letter_database.md', 'cover_letter_rules.md'):
            with open(os.path.join(defaults_dir, fname), 'w') as f:
                f.write(f'# {fname}\n\nPlaceholder content.\n')
        yield tmpdir
