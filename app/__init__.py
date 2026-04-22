"""Flask application factory."""

import logging
import sys
import traceback

from flask import Flask, jsonify

from app.config import Config


def create_app(config_class=Config):
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static',
    )
    app.config.from_object(config_class)
    app.config['TEMPLATES_AUTO_RELOAD'] = app.debug

    # --- Logging ---
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stderr,
        force=True,
    )
    app.logger.setLevel(logging.INFO)

    # --- Initialize database ---
    from app.models import init_db
    try:
        init_db()
        app.logger.info('Database initialized successfully')
    except Exception:
        app.logger.error('FATAL: init_db() failed')
        traceback.print_exc()
        raise

    # --- Template filters (shared across blueprints' render_template calls) ---
    from app.blueprints.helpers import md_bold
    app.jinja_env.filters['md_bold'] = md_bold

    # --- Inject current user into all templates ---
    @app.context_processor
    def inject_user():
        from flask import session as flask_session
        user_id = flask_session.get('user_id')
        if user_id:
            from app.models import get_user_by_id
            return {'user': get_user_by_id(user_id)}
        return {'user': None}

    # --- Health check endpoint ---
    @app.route('/health')
    def health():
        return jsonify({'status': 'ok'}), 200

    # --- Register blueprints ---
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.editor import bp as editor_bp
    from app.blueprints.settings import bp as settings_bp
    from app.blueprints.databases import bp as databases_bp
    from app.blueprints.jd import bp as jd_bp
    from app.blueprints.cover_letter import bp as cover_letter_bp
    from app.blueprints.versions import bp as versions_bp
    from app.blueprints.onboarding import bp as onboarding_bp
    from app.blueprints.parsers import bp as parsers_bp
    from app.blueprints.docs import bp as docs_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(editor_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(databases_bp)
    app.register_blueprint(jd_bp)
    app.register_blueprint(cover_letter_bp)
    app.register_blueprint(versions_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(parsers_bp)
    app.register_blueprint(docs_bp)

    return app
