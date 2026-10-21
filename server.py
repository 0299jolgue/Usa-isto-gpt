# Python 3.12 / ShardCloud / HTML forms backed by a Python TCP client
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import requests
from flask import Flask, render_template_string, request
from waitress import serve

from client import Version, run
from scid import ScidError, confirm as scid_confirm, start as scid_start

app = Flask(__name__)
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
<label for="email">Email</label><input id="email" name="email" type="email" required value="{{ email }}" autocomplete="email">
<button type="submit">Enviar PIN</button></form>
{% elif step == 'pin' %}
<p>Introduz o PIN enviado para {{ email }}.</p>
<form action="/auth/confirm" method="post"><input type="hidden" name="id" value="{{ challenge }}">
<label for="pin">PIN de seis dígitos</label><input id="pin" name="pin" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required autocomplete="one-time-code">
<button type="submit">Confirmar e entrar</button></form>
{% else %}
<p>A tentar entrar na sala. Esta página atualiza automaticamente.</p>
{% endif %}
{% if message %}<div class="message" role="status">{{ message }}</div>{% endif %}
{% if step != 'email' %}<p><a href="/">Começar de novo</a></p>{% endif %}
</main></body></html>"""


def page(step='email', message='', code='', email='', challenge='', refresh=False, status=200):
    return render_template_string(PAGE, step=step, message=message, code=code,
                                  email=email, challenge=challenge, refresh=refresh), status


@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/')
def index():
    return page()


@app.post('/auth/start')
def auth_start():
    code = request.form.get('code', '').strip().lstrip('#').upper()
    email = request.form.get('email', '').strip().lower()
    if not code or len(code) > 64 or any(not (c.isascii() and c.isalnum()) for c in code):
        return page(message='Código da sala inválido.', code=code, email=email, status=400)
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return page(message='Email inválido.', code=code, email=email, status=400)
    session = requests.Session()
    try:
        scid_start(session, email)
    except ScidError as exc:
        session.close()
        return page(message=str(exc), code=code, email=email)
    challenge = secrets.token_urlsafe(24)
    with lock:
        now = time.monotonic()
        for old_id in list(pending):
            if now - pending[old_id]['created'] > 600:
                pending.pop(old_id)['session'].close()
        pending[challenge] = {'email': email, 'code': code, 'session': session, 'created': now}
    return page(step='pin', email=email, challenge=challenge)


def execute(job_id, args):
    def emit(*parts):
        with lock:
            jobs[job_id]['lines'].append(' '.join(map(str, parts)))
    try:
        version = Version()
        for _ in range(2):
            if run(args, version, emit=emit):
                emit('Pedido concluído.')
                break
        else:
            raise RuntimeError('Não foi possível atualizar a versão')
    except Exception as exc:
        emit(f'Erro: {type(exc).__name__}: {exc}')
    finally:
        with lock:
            jobs[job_id]['done'] = True
        args.token = None


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
        hi, lo, token = scid_confirm(auth['session'], auth['email'], pin)
    except ScidError as exc:
        return page(message=str(exc), code=auth['code'], email=auth['email'])
    finally:
        auth['session'].close()
    job_id = secrets.token_urlsafe(24)
    with lock:
        now = time.monotonic()
        for old_id in list(jobs):
            if jobs[old_id]['done'] and now - jobs[old_id]['created'] > 900:
                del jobs[old_id]
        if sum(not job['done'] for job in jobs.values()) >= 2:
            return page(message='Já existem duas tentativas em curso. Aguarda um momento.', status=429)
        jobs[job_id] = {'lines': [], 'done': False, 'created': now}
    args = SimpleNamespace(code=auth['code'], hi=hi, lo=lo, token=token,
                           host='game.brawlstarsgame.com', port=9339)
    workers.submit(execute, job_id, args)
    return job_status(job_id)


@app.get('/status/<job_id>')
def job_status(job_id):
    with lock:
        job = jobs.get(job_id)
        if job is None:
            return page(message='Tentativa não encontrada.', status=404)
        lines, done = list(job['lines']), job['done']
    return page(step='status', message='\n'.join(lines) or 'A ligar ao servidor...', refresh=not done)


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8000')), threads=4)
