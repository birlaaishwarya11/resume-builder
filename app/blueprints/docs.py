"""Docs blueprint: landing page and product documentation."""

from flask import Blueprint, render_template

bp = Blueprint('docs', __name__)


@bp.route('/docs')
def docs_page():
    return render_template('docs.html')
