"""Application configuration loaded from environment variables."""

import os


class Config:
    """Base configuration. All values come from environment variables."""

    # Required in production -- no insecure fallbacks
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DATABASE_URL = os.environ.get('DATABASE_URL', '')
    FERNET_KEY = os.environ.get('FERNET_KEY', '')

    # Data directory for per-user files (resume YAML, PDFs, databases)
    DATA_DIR = os.environ.get('DATA_DIR', os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'
    ))

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB upload limit

    # PDF rendering defaults
    DEFAULT_STYLE = {
        'font_family': '"Times New Roman", Times, serif',
        'font_size': '10pt',
        'line_height': '1.15',
        'margin': '0.4in',
        'accent_color': '#000000',
    }
