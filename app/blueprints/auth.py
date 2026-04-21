"""Authentication blueprint: signup, login, logout."""

from flask import Blueprint, render_template, request, session, redirect, url_for

from app.models import create_user, authenticate_user

bp = Blueprint('auth', __name__)


@bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    if not name or not email or not password:
        return render_template('signup.html', error='All fields are required.')
    if len(password) < 6:
        return render_template('signup.html', error='Password must be at least 6 characters.')

    user_id = create_user(name, email, password)
    if user_id is None:
        return render_template('signup.html', error='An account with this email already exists.')

    session['user_id'] = user_id
    return redirect(url_for('onboarding.onboarding_page'))


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    user = authenticate_user(email, password)
    if not user:
        return render_template('login.html', error='Invalid email or password.')

    session['user_id'] = user['id']
    return redirect(url_for('editor.index'))


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
