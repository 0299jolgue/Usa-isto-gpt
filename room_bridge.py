# Python 3.12 / Flask / room invite queue for the LDPhone agent
"""Relay official Brawl Stars room links to a running Android device."""

import hmac
import re
import secrets
import threading
import time
from collections import deque
from urllib.parse import parse_qs, urlparse
from flask import Blueprint, jsonify, redirect, render_template_string, request

bridge = Blueprint('bridge', __name__)
_lock = threading.RLock()
_agent_token = None
_last_seen = 0.0
_jobs = {}
_pending = deque()
_CODE = re.compile(r'^X[QWERTYUPASDFGHJKLZCVBNM23456789]{2,12}$')
_LABELS = {
    'queued': 'À espera do LDPhone',
    'running': 'A abrir o convite',
    'sent': 'Convite aberto; entrada ainda não confirmada',
    'observed': 'Pedido de entrada enviado pelo jogo; confirma a sala no ecrã',
    'failed': 'Não foi possível abrir o convite',
    'tapped': 'Toque em Jogar enviado ao LDPhone; confirma no jogo',
}
_PAGE = '''<!doctype html><html lang="pt"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Entrar na sala</title><style>body{font:17px system-ui;max-width:520px;margin:2rem auto;padding:0 1rem}
input,button{font:inherit;padding:.7rem;margin:.35rem 0;width:100%;box-sizing:border-box}
p{line-height:1.5}pre{white-space:pre-wrap;word-break:break-all;background:#eee;padding:1rem}</style>
<h1>Entrar na sala</h1><p>LDPhone: {{ 'ligado' if online else 'desligado' }}</p>
{% if not online %}<p>Uma vez no Termux do LDPhone, executa:</p>
<pre>curl -fsSL {{ base }}/agent.py -o /sdcard/Download/ldphone_agent.py &amp;&amp; python /sdcard/Download/ldphone_agent.py {{ base }}</pre>
<p>Deixa o agente a correr. Esta página mostra “ligado” automaticamente.</p>
<script>setInterval(async()=>{try{let r=await fetch('/bridge/online');if((await r.json()).online)location.reload()}catch(e){}},3000)</script>{% endif %}
<form method="post" action="/bridge/join"><input name="code" placeholder="Código ou link da sala" required>
<button>Entrar com a conta do LDPhone</button></form>
<form method="post" action="/bridge/play"><button>Iniciar partida no LDPhone</button></form></html>'''


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


def _agent():
    token = request.headers.get('Authorization', '').removeprefix('Bearer ')
    return bool(_agent_token and hmac.compare_digest(token, _agent_token))


@bridge.get('/bridge')
def home():
    with _lock:
        return render_template_string(_PAGE, online=time.monotonic() - _last_seen < 15,
                                      base='https://' + request.host.split(':', 1)[0])


@bridge.get('/bridge/online')
def online():
    with _lock:
        return jsonify(online=time.monotonic() - _last_seen < 15)


@bridge.post('/bridge/register')
def register():
    global _agent_token, _last_seen
    data = request.get_json(silent=True) or {}
    token = str(data.get('token', ''))
    if not 32 <= len(token) <= 128:
        return jsonify(error='invalid registration'), 400
    with _lock:
        if _agent_token and not hmac.compare_digest(token, _agent_token) and time.monotonic() - _last_seen < 30:
            return jsonify(error='another agent already active'), 409
        if _agent_token and not hmac.compare_digest(token, _agent_token):
            _pending.clear()
        _agent_token, _last_seen = token, time.monotonic()
    return jsonify(ok=True)


@bridge.post('/bridge/join')
def join():
    try:
        code = normalize_code(request.form.get('code', ''))
    except ValueError:
        return jsonify(error='invalid room code'), 400
    with _lock:
        if len(_pending) >= 4:
            return jsonify(error='queue full'), 429
        job_id = secrets.token_urlsafe(12)
        _jobs[job_id] = {'action': 'join', 'code': code, 'status': 'queued', 'created': time.monotonic()}
        _pending.append(job_id)
    return redirect(f'/bridge/job/{job_id}', code=303)


@bridge.post('/bridge/play')
def play():
    with _lock:
        if len(_pending) >= 4:
            return jsonify(error='queue full'), 429
        job_id = secrets.token_urlsafe(12)
        _jobs[job_id] = {'action': 'play', 'status': 'queued', 'created': time.monotonic()}
        _pending.append(job_id)
    return redirect(f'/bridge/job/{job_id}', code=303)


@bridge.get('/bridge/job/<job_id>')
def job_page(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error='unknown job'), 404
        action, state = job['action'], job['status']
        title = 'Sala ' + job['code'] if action == 'join' else 'Iniciar partida'
        label = ('A tocar em Jogar' if state == 'running' and action == 'play'
                 else _LABELS.get(state, state))
        if state == 'queued' and time.monotonic() - _last_seen >= 15:
            label = 'LDPhone desligado; inicia o agente no Termux'
    return f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><h1>{title}</h1>
<p id="status">{label}</p><a href="/bridge">Voltar</a><script>
setInterval(async()=>{{let r=await fetch('/bridge/status/{job_id}');if(r.ok){{let j=await r.json();
document.getElementById('status').textContent=j.label+(j.detail?' — '+j.detail:'');}}}},2000)
</script>'''


@bridge.get('/bridge/status/<job_id>')
def status(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error='unknown job'), 404
        if job['status'] in ('queued', 'running') and time.monotonic() - job['created'] > 90:
            job['status'] = 'failed'
            job['detail'] = 'Tempo esgotado sem confirmação do agente.'
        label = ('A tocar em Jogar' if job['status'] == 'running' and job['action'] == 'play'
                 else _LABELS.get(job['status'], job['status']))
        if job['status'] == 'queued' and time.monotonic() - _last_seen >= 15:
            label = 'LDPhone desligado; inicia o agente no Termux'
        return jsonify(status=job['status'], label=label,
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
                return jsonify(id=job_id, action=job['action'], code=job.get('code'))
    return jsonify(job=None)


@bridge.post('/bridge/result/<job_id>')
def result(job_id):
    if not _agent():
        return jsonify(error='unauthorized'), 401
    data = request.get_json(silent=True) or {}
    state = data.get('status')
    if state not in ('sent', 'observed', 'tapped', 'failed'):
        return jsonify(error='invalid status'), 400
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error='unknown job'), 404
        job['status'] = state
        job['detail'] = str(data.get('detail', ''))[:200]
    return jsonify(ok=True)
