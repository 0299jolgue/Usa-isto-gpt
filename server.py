# Python 3.12 / ShardCloud / Brawl Stars room bridge website
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash
from room_bridge import _agent, _touch, bridge

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('PANEL_SESSION_SECRET') or secrets.token_hex(32)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.register_blueprint(bridge)
log = logging.getLogger('brawl-room')
_PASSWORD_HASH = 'pbkdf2:sha256:600000$5fYyRVIzm6kx6IEE$3044c87a7ccdf0c49cd87fc754e1afee3780e8822c53cd4dd24953627a968eb8'
_login_attempts = defaultdict(deque)


@app.context_processor
def template_security():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(24)
    return {'csrf_token': session['csrf']}


@app.before_request
def require_login():
    public = {'health', 'agent_script', 'login', 'static', 'bridge.register',
              'bridge.next_job', 'bridge.result', 'bridge.upload_screenshot',
              'bridge.farm_state', 'bridge.trophies_report',
              'ai_ready', 'ai_step'}
    if request.endpoint in public:
        return None
    if not session.get('logged_in'):
        return redirect(url_for('login', next=request.path))
    if request.method == 'POST' and request.endpoint != 'logout':
        given = request.form.get('csrf', '')
        if not secrets.compare_digest(given, session.get('csrf', '')):
            return 'Pedido expirado. Atualiza a página e tenta novamente.', 403


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html', error=None)
    ip = request.headers.get('CF-Connecting-IP', request.remote_addr or 'unknown')
    attempts = _login_attempts[ip]
    now = time.monotonic()
    while attempts and now - attempts[0] > 300:
        attempts.popleft()
    if len(attempts) >= 8:
        return render_template('login.html', error='Muitas tentativas. Aguarda alguns minutos.'), 429
    username = request.form.get('username', '')
    password = request.form.get('password', '')
    expected_user = os.environ.get('PANEL_USERNAME', 'jolgue')
    expected_password = os.environ.get('PANEL_PASSWORD')
    valid_password = (secrets.compare_digest(password, expected_password) if expected_password
                      else check_password_hash(_PASSWORD_HASH, password))
    if not secrets.compare_digest(username, expected_user) or not valid_password:
        attempts.append(now)
        return render_template('login.html', error='Login ou senha incorretos.'), 401
    attempts.clear()
    session.clear()
    session['logged_in'] = True
    session['csrf'] = secrets.token_urlsafe(24)
    destination = request.args.get('next', '')
    return redirect(destination if destination.startswith('/') and not destination.startswith('//')
                    else url_for('bridge.home'), code=303)


@app.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'), code=303)


@app.get('/')
def index():
    return redirect('/bridge', code=302)


@app.get('/health')
def health():
    return 'ok', 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.get('/agent.py')
def agent_script():
    return send_file('ldphone_agent.py', mimetype='text/x-python; charset=utf-8')


@app.post('/ai/ready')
def ai_ready():
    device = _agent()
    if not device:
        return jsonify(error='unauthorized'), 401
    _touch(device['id'])
    try:
        from ai_engine import ready
        from pyla_state import _source_template, STATES
        ready()
        for _, path, _, _ in STATES:
            _source_template(path)
        return jsonify(ok=True)
    except Exception as exc:
        log.exception('ai_ready_failed')
        return jsonify(error=f'{type(exc).__name__}: {exc}'), 503


@app.post('/ai/step')
def ai_step():
    device = _agent()
    if not device:
        return jsonify(error='unauthorized'), 401
    _touch(device['id'])
    if request.mimetype != 'image/png':
        return jsonify(error='expected image/png'), 415
    try:
        from ai_engine import decide
        return jsonify(decide(request.get_data(cache=False)))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        log.exception('ai_step_failed')
        return jsonify(error=f'{type(exc).__name__}: {exc}'), 503
