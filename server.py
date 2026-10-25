# Python 3.12 / ShardCloud / HTML forms backed by a Python TCP client
import os
import re
import logging
import hmac
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import requests
from flask import Flask, jsonify, redirect, render_template_string, request, send_file, url_for
from waitress import serve

from client import Version, run
from scid import ScidError, confirm as scid_confirm, start as scid_start
from room_bridge import bridge

app = Flask(__name__)
app.register_blueprint(bridge)
log = logging.getLogger('brawl-room')
lock = threading.Lock()
pending = {}
jobs = {}
workers = ThreadPoolExecutor(max_workers=2)

PAGE = """<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{% if refresh %}<meta http-equiv="refresh" content="2">{% endif %}
<title>Entrar na sala · Brawl Stars</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#f2f5ff;background:#0c1224}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px}
main{width:min(100%,470px);background:#18213a;border:1px solid #314168;border-radius:20px;padding:28px;box-shadow:0 20px 50px #05091366}
h1{margin:0 0 8px;font-size:1.7rem}p{color:#b8c4df;margin:0 0 22px;line-height:1.5}
label{display:block;font-weight:650;margin:16px 0 7px}input{width:100%;padding:13px 14px;border:1px solid #506189;border-radius:10px;background:#10182b;color:white;font:inherit}
button{width:100%;border:0;border-radius:10px;background:#ffc928;color:#16203c;font-weight:800;font:inherit;padding:14px;margin-top:22px;cursor:pointer}
.message{white-space:pre-wrap;overflow-wrap:anywhere;background:#10182b;border-radius:10px;padding:14px;margin-top:18px;line-height:1.5}
a{color:#9cc8ff}
</style></head><body><main>
<h1>Entrar na sala</h1>
{% if step == 'email' %}
<p>Introduz o código da sala e o email da conta Supercell ID.</p>
<form action="/auth/start" method="post">
<label for="code">Código da sala</label><input id="code" name="code" maxlength="64" required value="{{ code }}" autocapitalize="characters">
{% if not vercel_mode %}
<label for="email">Email</label><input id="email" name="email" type="email" required value="{{ email }}" autocomplete="email">
<button type="submit">Enviar PIN</button>
{% endif %}
<button type="submit" formaction="/guest" formmethod="post" formnovalidate>Entrar com conta convidada</button></form>
{% elif step == 'pin' %}
<p>Introduz o PIN enviado para {{ email }}.</p>
<form action="/auth/confirm" method="post"><input type="hidden" name="id" value="{{ challenge }}">
<label for="pin">PIN de seis dígitos</label><input id="pin" name="pin" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required autocomplete="one-time-code">
<button type="submit">Confirmar e entrar</button></form>
{% else %}
<p>Resultado da tentativa de entrada na sala.</p>
{% endif %}
{% if message %}<div class="message" role="status">{{ message }}</div>{% endif %}
{% if step != 'email' %}<p><a href="/">Começar de novo</a></p>{% endif %}
</main></body></html>"""


def page(step='email', message='', code='', email='', challenge='', refresh=False, status=200):
    return render_template_string(PAGE, step=step, message=message, code=code,
                                  email=email, challenge=challenge, refresh=refresh,
                                  vercel_mode=bool(os.environ.get('VERCEL'))), status


@app.after_request
def no_cache(response):
    log.info('http_response method=%s path=%s status=%s', request.method, request.path, response.status_code)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/')
def index():
    return redirect('/bridge', code=302)


@app.get('/health')
def health():
    return 'ok', 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.get('/tools/dump_libg_tail.py')
def dump_helper():
    return send_file('dump_libg_tail.py', mimetype='text/x-python; charset=utf-8')


@app.get('/tools/dump_libg_code.py')
def dump_code_helper():
    return send_file('dump_libg_code.py', mimetype='text/x-python; charset=utf-8')


@app.get('/tools/brawl_spy.py')
def brawl_spy_helper():
    return send_file('brawl_spy.py', mimetype='text/x-python; charset=utf-8')


@app.get('/tools/capture_login.py')
def capture_helper():
    return 'Captura suspensa.', 410, {'Content-Type': 'text/plain; charset=utf-8'}


@app.post('/auth/start')
def auth_start():
    code = request.form.get('code', '').strip().lstrip('#').upper()
    email = request.form.get('email', '').strip().lower()
    if not code or len(code) > 64 or any(not (c.isascii() and c.isalnum()) for c in code):
        return page(message='Código da sala inválido.', code=code, email=email, status=400)
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return page(message='Email inválido.', code=code, email=email, status=400)
    session = requests.Session()
    log.info('scid_start_requested')
    try:
        scid_start(session, email)
    except ScidError as exc:
        log.warning('scid_start_failed reason=%s', exc)
        session.close()
        return page(message=str(exc), code=code, email=email)
    challenge = secrets.token_urlsafe(24)
    with lock:
        now = time.monotonic()
        for old_id in list(pending):
            if now - pending[old_id]['created'] > 600:
                pending.pop(old_id)['session'].close()
        pending[challenge] = {'email': email, 'code': code, 'session': session, 'created': now}
    log.info('scid_pin_requested')
    return page(step='pin', email=email, challenge=challenge)


def execute(job_id, args):
    def emit(*parts):
        line = ' '.join(map(str, parts))
        log.info('tcp_job %s', line)
        with lock:
            jobs[job_id]['lines'].append(line)
    try:
        version = Version()
        for _ in range(2):
            if run(args, version, emit=emit):
                emit('Pedido concluído.')
                break
        else:
            raise RuntimeError('Não foi possível atualizar a versão')
    except Exception as exc:
        log.exception('tcp_job_failed')
        emit(f'Erro: {type(exc).__name__}: {exc}')
    finally:
        with lock:
            jobs[job_id]['done'] = True
        args.token = None


def schedule_join(code, hi, lo, token):
    job_id = secrets.token_urlsafe(24)
    with lock:
        now = time.monotonic()
        for old_id in list(jobs):
            if jobs[old_id]['done'] and now - jobs[old_id]['created'] > 900:
                del jobs[old_id]
        if sum(not job['done'] for job in jobs.values()) >= 2:
            return None
        jobs[job_id] = {'lines': [], 'done': False, 'created': now}
    args = SimpleNamespace(code=code, hi=hi, lo=lo, token=token,
                           host='game.brawlstarsgame.com', port=9339)
    log.info('tcp_job_scheduled guest=%s', token is None)
    workers.submit(execute, job_id, args)
    return redirect(url_for('job_status', job_id=job_id), code=303)


@app.post('/guest')
def guest_join():
    code = request.form.get('code', '').strip().lstrip('#').upper()
    if not code or len(code) > 64 or any(not (c.isascii() and c.isalnum()) for c in code):
        return page(message='Código da sala inválido.', code=code, status=400)
    if os.environ.get('VERCEL'):
        result = probe(code)
        return page(step='status', message='\n'.join(result['events']) or 'Sem resposta do servidor.')
    result = schedule_join(code, 0, 0, None)
    return result or page(message='Já existem duas tentativas em curso. Aguarda um momento.', code=code, status=429)


def probe(code, key_version=None, pad_bytes=0, crypto_mode='v3'):
    args = SimpleNamespace(code=code, hi=0, lo=0, token=None,
                           host='game.brawlstarsgame.com', port=9339,
                           deadline=time.monotonic() + 18, pad_bytes=pad_bytes,
                           crypto_mode=crypto_mode)
    events = []
    version = Version()
    if key_version is not None:
        version.key_version = key_version
    start = time.monotonic()
    accepted = False
    try:
        for _ in range(2):
            if run(args, version, emit=lambda *parts: events.append(' '.join(map(str, parts)))):
                accepted = True
                break
    except Exception as exc:
        log.exception('vercel_guest_probe_failed')
        events.append(f'Erro: {type(exc).__name__}: {exc}')
    return {'ok': accepted, 'events': events, 'elapsed_seconds': round(time.monotonic() - start, 2),
            'client_version': f'{version.major}.{version.minor}.{version.build}', 'protocol': 2,
            'key_version': version.key_version, 'asset_sha': version.sha}


@app.get('/api/probe')
def api_probe():
    expected = os.environ.get('PROBE_KEY', '')
    supplied = request.args.get('key', '')
    if not expected or not hmac.compare_digest(supplied, expected):
        return jsonify({'error': 'unauthorized'}), 401
    code = request.args.get('code', '').strip().lstrip('#').upper()
    if not code or len(code) > 64 or any(not (c.isascii() and c.isalnum()) for c in code):
        return jsonify({'error': 'invalid_room_code'}), 400
    key_version = request.args.get('key_version')
    if key_version is not None:
        if not key_version.isdecimal() or not 40 <= int(key_version) <= 70:
            return jsonify({'error': 'invalid_key_version'}), 400
        key_version = int(key_version)
    pad_bytes = request.args.get('pad_bytes', '0')
    if not pad_bytes.isdecimal() or not 0 <= int(pad_bytes) <= 700:
        return jsonify({'error': 'invalid_pad_bytes'}), 400
    crypto_mode = request.args.get('crypto_mode', 'v3')
    if crypto_mode not in ('v3', 'salsa20'):
        return jsonify({'error': 'invalid_crypto_mode'}), 400
    return jsonify(probe(code, key_version, int(pad_bytes), crypto_mode))


@app.post('/auth/confirm')
def auth_confirm():
    challenge = request.form.get('id', '')
    pin = request.form.get('pin', '')
    if not re.fullmatch(r'[0-9]{6}', pin):
        return page(step='pin', challenge=challenge, message='PIN inválido.', status=400)
    with lock:
        auth = pending.pop(challenge, None)
    if auth is None or time.monotonic() - auth['created'] > 600:
        return page(message='Sessão expirada. Pede um novo PIN.', status=400)
    try:
        log.info('scid_pin_confirmation_requested')
        hi, lo, token = scid_confirm(auth['session'], auth['email'], pin)
    except ScidError as exc:
        log.warning('scid_pin_confirmation_failed reason=%s', exc)
        return page(message=str(exc), code=auth['code'], email=auth['email'])
    finally:
        auth['session'].close()
    result = schedule_join(auth['code'], hi, lo, token)
    return result or page(message='Já existem duas tentativas em curso. Aguarda um momento.', status=429)


@app.get('/status/<job_id>')
def job_status(job_id):
    with lock:
        job = jobs.get(job_id)
        if job is None:
            return page(message='Tentativa não encontrada.', status=404)
        lines, done = list(job['lines']), job['done']
    return page(step='status', message='\n'.join(lines) or 'A ligar ao servidor...', refresh=not done)


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', '80')), threads=4)
