# Python 3.11+ / Flask service / official Brawl Stars room invite relay
"""Queue room invitations for a paired Android agent."""

import hmac
import os
import re
import secrets
import threading
import time
from collections import deque
from flask import Blueprint, jsonify, make_response, redirect, render_template_string, request
from urllib.parse import parse_qs, urlparse

bridge = Blueprint('bridge', __name__)
_lock = threading.RLock()
_agent_token = None
_pair_code = None
_browser_token = None
_jobs = {}
_pending = deque()
_last_seen = 0.0
_CODE = re.compile(r'^X[QWERTYUPASDFGHJKLZCVBNM23456789]{2,12}$')
_LABELS = {
    'queued': 'À espera do LDPhone',
    'running': 'A abrir o convite',
    'sent': 'Convite aberto; entrada ainda não confirmada',
    'observed': 'Pedido de entrada enviado pelo jogo; confirma a sala no ecrã',
    'failed': 'Não foi possível abrir o convite',
}
_PAGE = '''<!doctype html><html lang="pt"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Entrar na sala</title><style>body{font:17px system-ui;max-width:520px;margin:2rem auto;padding:0 1rem}
input,button{font:inherit;padding:.7rem;margin:.35rem 0;width:100%;box-sizing:border-box}p{line-height:1.5}</style>
<h1>Entrar na sala</h1>{% if paired %}<p>LDPhone: {{ 'ligado' if online else 'sem ligação recente' }}</p>
<form method="post" action="/bridge/join"><input name="code" placeholder="Código ou link da sala" required>
<button>Entrar com a conta do LDPhone</button></form>
{% else %}<p>Inicia o agente no LDPhone e escreve aqui o código de emparelhamento que ele mostra.</p>
<form method="post" action="/bridge/pair"><input name="pair_code" placeholder="Código de emparelhamento" required>
<button>Emparelhar</button></form>{% endif %}{% if message %}<p>{{ message }}</p>{% endif %}</html>'''


def _paired():
    token = request.cookies.get('bridge_session', '')
    return bool(_browser_token and hmac.compare_digest(token, _browser_token))


def _agent():
    token = request.headers.get('Authorization', '').removeprefix('Bearer ')
    return bool(_agent_token and hmac.compare_digest(token, _agent_token))


def normalize_code(value):
    value = value.strip()
    if value.startswith('https://'):
        parsed = urlparse(value)
        if parsed.hostname != 'link.brawlstars.com' or not parsed.path.startswith('/invite/gameroom/'):
            raise ValueError('invalid room link')
        value = parse_qs(parsed.query).get('tag', [''])[0]
    code = value.lstrip('#').upper()
    if not _CODE.fullmatch(code):
        raise ValueError('invalid room code')
    return code


@bridge.get('/bridge')
def home():
    with _lock:
        return render_template_string(_PAGE, paired=_paired(),
                                      online=time.monotonic() - _last_seen < 15, message=request.args.get('message', ''))


@bridge.post('/bridge/register')
def register():
    global _agent_token, _pair_code, _browser_token, _last_seen
    data = request.get_json(silent=True) or {}
    token = str(data.get('token', ''))
    pair_code = str(data.get('pair_code', ''))
    if len(token) < 32 or len(token) > 128 or not re.fullmatch(r'[A-Z0-9]{8}', pair_code):
        return jsonify(error='invalid registration'), 400
    with _lock:
        if _agent_token and not hmac.compare_digest(token, _agent_token) and time.monotonic() - _last_seen < 30:
            return jsonify(error='agent already registered'), 409
        if _agent_token and not hmac.compare_digest(token, _agent_token):
            _browser_token = None
            _pending.clear()
        _agent_token, _pair_code, _last_seen = token, pair_code, time.monotonic()
        return jsonify(ok=True)


@bridge.post('/bridge/pair')
def pair():
    global _browser_token, _pair_code
    code = request.form.get('pair_code', '').strip().upper()
    with _lock:
        if not _pair_code or not hmac.compare_digest(code, _pair_code):
            return redirect('/bridge?message=C%C3%B3digo+incorreto', code=303)
        _pair_code = None
        _browser_token = secrets.token_urlsafe(32)
        response = make_response(redirect('/bridge', code=303))
        response.set_cookie('bridge_session', _browser_token, httponly=True, secure=request.is_secure,
                            samesite='Lax', max_age=86400)
        return response


@bridge.post('/bridge/join')
def join():
    if not _paired():
        return jsonify(error='pair first'), 403
    try:
        code = normalize_code(request.form.get('code', ''))
    except ValueError:
        return jsonify(error='invalid room code'), 400
    with _lock:
        if len(_pending) >= 4:
            return jsonify(error='queue full'), 429
        job_id = secrets.token_urlsafe(12)
        _jobs[job_id] = {'code': code, 'status': 'queued', 'created': time.monotonic()}
        _pending.append(job_id)
    return redirect(f'/bridge/job/{job_id}', code=303)


@bridge.get('/bridge/job/<job_id>')
def job_page(job_id):
    if not _paired():
        return jsonify(error='pair first'), 403
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error='unknown job'), 404
        code, state = job['code'], job['status']
        label = _LABELS.get(state, state)
    return f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><h1>Sala {code}</h1>
<p id="status">{label}</p><a href="/bridge">Voltar</a><script>
setInterval(async()=>{{let r=await fetch('/bridge/status/{job_id}');if(r.ok){{let j=await r.json();
document.getElementById('status').textContent=j.label+(j.detail?' — '+j.detail:'');}}}},2000)
</script>'''


@bridge.get('/bridge/status/<job_id>')
def status(job_id):
    if not _paired():
        return jsonify(error='pair first'), 403
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error='unknown job'), 404
        if job['status'] in ('queued', 'running') and time.monotonic() - job['created'] > 90:
            job['status'] = 'failed'
            job['detail'] = 'Tempo esgotado sem confirmação do agente.'
        return jsonify(status=job['status'], label=_LABELS.get(job['status'], job['status']),
                       detail=job.get('detail', ''))


@bridge.get('/bridge/next')
def next_job():
    global _last_seen
    if not _agent():
        return jsonify(error='unauthorized'), 401
    with _lock:
        _last_seen = time.monotonic()
        while _pending:
            job_id = _pending.popleft()
            job = _jobs.get(job_id)
            if job and job['status'] == 'queued':
                job['status'] = 'running'
                return jsonify(id=job_id, code=job['code'])
    return jsonify(job=None)


@bridge.post('/bridge/result/<job_id>')
def result(job_id):
    if not _agent():
        return jsonify(error='unauthorized'), 401
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in ('sent', 'observed', 'failed'):
        return jsonify(error='invalid status'), 400
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error='unknown job'), 404
        job['status'] = status
        job['detail'] = str(data.get('detail', ''))[:200]
    return jsonify(ok=True)
