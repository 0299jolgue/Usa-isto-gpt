# Python 3.12 / Flask / multi-device Brawl Stars control panel
"""Pair Android agents, queue actions per device, and show account snapshots."""
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen
from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for

bridge = Blueprint('bridge', __name__)
_lock = threading.RLock()
_pairs, _jobs, _groups = {}, {}, {}
_pending = defaultdict(deque)
_CODE = re.compile(r'^X[QWERTYUPASDFGHJKLZCVBNM23456789]{2,12}$')
_TAG = re.compile(r'^#[0289PYLQGRJCUV]{3,14}$')
_STATE_DIR = Path(os.environ.get('BRAWL_STATE_DIR', '/tmp/brawl-room-data'))
_STATE_DIR.mkdir(parents=True, exist_ok=True)
_STATE_DIR.chmod(0o700)
_DB = _STATE_DIR / 'state.sqlite3'
_SCREENS = _STATE_DIR / 'screens'
_SCREENS.mkdir(exist_ok=True)
_SCREENS.chmod(0o700)
_TERMINAL = {'sent', 'observed', 'tapped', 'complete', 'failed'}


@contextmanager
def _db():
    con = sqlite3.connect(_DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


with _db() as _con:
    _con.executescript('''
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL, player_tag TEXT NOT NULL DEFAULT '',
            trophies INTEGER, trophies_at REAL, last_seen REAL NOT NULL DEFAULT 0,
            screenshot_at REAL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
_DB.chmod(0o600)


def _devices():
    with _db() as con:
        rows = con.execute('SELECT id,name,player_tag,trophies,trophies_at,last_seen,screenshot_at '
                           'FROM devices ORDER BY rowid').fetchall()
    return [dict(row) | {'online': time.time() - row['last_seen'] < 18} for row in rows]


def _device(device_id):
    with _db() as con:
        row = con.execute('SELECT * FROM devices WHERE id=?', (device_id,)).fetchone()
    return dict(row) if row else None


def _agent():
    token = request.headers.get('Authorization', '').removeprefix('Bearer ')
    if not 32 <= len(token) <= 128:
        return None
    with _db() as con:
        row = con.execute('SELECT id,name FROM devices WHERE token_hash=?',
                          (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return dict(row) if row else None


def _touch(device_id):
    with _db() as con:
        con.execute('UPDATE devices SET last_seen=? WHERE id=?', (time.time(), device_id))


def normalize_code(value):
    value = value.strip()
    if value.startswith('https://'):
        parsed = urlparse(value)
        if parsed.hostname != 'link.brawlstars.com' or not parsed.path.startswith('/invite/gameroom/'):
            raise ValueError('Link de sala inválido.')
        value = parse_qs(parsed.query).get('tag', [''])[0]
    code = value.lstrip('#').upper()
    if not _CODE.fullmatch(code):
        raise ValueError('Código da sala inválido.')
    return code


def _job_label(job):
    state = job['status']
    if state == 'running':
        return {'join': 'A abrir o convite', 'play': 'A tocar em Jogar',
                'ai': 'A analisar imagens', 'snapshot': 'A tirar print'}[job['action']]
    if state == 'queued' and time.time() - _device(job['device_id'])['last_seen'] > 18:
        return 'LDPhone desligado'
    return {'queued': 'À espera do LDPhone', 'sent': 'Convite aberto',
            'observed': 'Pedido de entrada observado', 'tapped': 'Toque em Jogar enviado',
            'complete': 'Concluído', 'failed': 'Falhou'}.get(state, state)


def _group_status(group):
    children = [_jobs[job_id] for job_id in group['children']]
    states = [job['status'] for job in children]
    if all(state in _TERMINAL for state in states):
        overall = 'failed' if all(state == 'failed' for state in states) else 'complete'
    elif any(state == 'running' for state in states):
        overall = 'running'
    else:
        overall = 'queued'
    return {'status': overall, 'devices': [
        {'name': job['name'], 'status': job['status'], 'label': _job_label(job),
         'detail': job.get('detail', '')} for job in children]}


def _enqueue(action, target, code=None):
    devices = _devices()
    selected = ([device for device in devices if device['online']] if target == 'all'
                else [device for device in devices if device['id'] == target])
    if not selected:
        raise ValueError('Não há telemóveis disponíveis para esta ação.')
    with _lock:
        if any(len(_pending[device['id']]) >= 4 for device in selected):
            raise ValueError('Há demasiadas ações em espera para um telemóvel.')
        group_id = secrets.token_urlsafe(12)
        group = {'action': action, 'code': code, 'children': [], 'created': time.time()}
        _groups[group_id] = group
        for device in selected:
            job_id = secrets.token_urlsafe(12)
            _jobs[job_id] = {'action': action, 'code': code, 'device_id': device['id'],
                             'name': device['name'], 'status': 'queued', 'created': time.time()}
            _pending[device['id']].append(job_id)
            group['children'].append(job_id)
    return group_id


@bridge.get('/bridge')
def home():
    with _lock:
        for code, expiry in list(_pairs.items()):
            if expiry < time.time():
                del _pairs[code]
        pair = secrets.token_urlsafe(8)
        _pairs[pair] = time.time() + 600
    with _db() as con:
        has_key = bool(con.execute('SELECT value FROM settings WHERE key=?', ('brawl_api_key',)).fetchone())
    return render_template('bridge.html', devices=_devices(), pair=pair, has_key=has_key,
                           base='https://' + request.host.split(':', 1)[0])


@bridge.get('/bridge/online')
def online():
    devices = _devices()
    return jsonify(online=sum(device['online'] for device in devices), total=len(devices))


@bridge.post('/bridge/register')
def register():
    data = request.get_json(silent=True) or {}
    token = str(data.get('token', ''))
    if not 32 <= len(token) <= 128:
        return jsonify(error='invalid token'), 400
    digest = hashlib.sha256(token.encode()).hexdigest()
    with _db() as con:
        row = con.execute('SELECT id,name,player_tag FROM devices WHERE token_hash=?', (digest,)).fetchone()
        if row:
            con.execute('UPDATE devices SET last_seen=? WHERE id=?', (time.time(), row['id']))
            return jsonify(ok=True, id=row['id'], name=row['name'], player_tag=row['player_tag'])
    pair = str(data.get('pair', ''))
    with _lock:
        if _pairs.get(pair, 0) < time.time():
            return jsonify(error='pairing code missing or expired'), 403
    with _db() as con:
        count = con.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
        device_id, name = secrets.token_urlsafe(9), f'LDPhone {count + 1}'
        con.execute('INSERT INTO devices(id,token_hash,name,last_seen) VALUES(?,?,?,?)',
                    (device_id, digest, name, time.time()))
    return jsonify(ok=True, id=device_id, name=name, player_tag='')


@bridge.post('/bridge/device/<device_id>/profile')
def profile(device_id):
    if not _device(device_id):
        return 'Telemóvel desconhecido', 404
    name = request.form.get('name', '').strip()[:40]
    tag = request.form.get('player_tag', '').strip().upper()
    if not name or (tag and not _TAG.fullmatch(tag)):
        flash('Nome ou tag de jogador inválidos.')
        return redirect(url_for('bridge.home'), code=303)
    with _db() as con:
        con.execute('UPDATE devices SET name=?,player_tag=?,trophies=NULL,trophies_at=NULL WHERE id=?',
                    (name, tag, device_id))
    flash('Conta atualizada.')
    return redirect(url_for('bridge.home'), code=303)


@bridge.post('/bridge/device/<device_id>/remove')
def remove_device(device_id):
    device = _device(device_id)
    if not device:
        return 'Telemóvel desconhecido', 404
    with _lock:
        _pending.pop(device_id, None)
        for job in _jobs.values():
            if job['device_id'] == device_id and job['status'] not in _TERMINAL:
                job['status'], job['detail'] = 'failed', 'Telemóvel removido do painel.'
    with _db() as con:
        con.execute('DELETE FROM devices WHERE id=?', (device_id,))
    (_SCREENS / (device_id + '.png')).unlink(missing_ok=True)
    flash(f'{device["name"]} removido. Podes emparelhá-lo novamente.')
    return redirect(url_for('bridge.home'), code=303)


@bridge.post('/bridge/api-key')
def api_key():
    key = request.form.get('api_key', '').strip()
    with _db() as con:
        if request.form.get('remove') == '1':
            con.execute('DELETE FROM settings WHERE key=?', ('brawl_api_key',))
            flash('Chave da API removida.')
        elif key:
            con.execute('INSERT INTO settings(key,value) VALUES(?,?) '
                        'ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('brawl_api_key', key))
            flash('Chave da API guardada no servidor.')
        else:
            flash('Cola a chave da API antes de guardar.')
    return redirect(url_for('bridge.home'), code=303)


@bridge.post('/bridge/device/<device_id>/trophies')
def refresh_trophies(device_id):
    device = _device(device_id)
    if not device:
        return 'Telemóvel desconhecido', 404
    with _db() as con:
        row = con.execute('SELECT value FROM settings WHERE key=?', ('brawl_api_key',)).fetchone()
    if not row or not device['player_tag']:
        flash('Define a tag da conta e a chave da API para ver os troféus.')
        return redirect(url_for('bridge.home'), code=303)
    url = 'https://api.brawlstars.com/v1/players/' + quote(device['player_tag'], safe='')
    req = Request(url, headers={'Authorization': 'Bearer ' + row['value'], 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=10) as response:
            import json
            payload = json.load(response)
        trophies = payload.get('trophies')
        if not isinstance(trophies, int) or trophies < 0:
            raise ValueError('Resposta sem troféus')
        with _db() as con:
            con.execute('UPDATE devices SET trophies=?,trophies_at=? WHERE id=?',
                        (trophies, time.time(), device_id))
        flash(f'{device["name"]}: {trophies:,} troféus.'.replace(',', ' '))
    except HTTPError as exc:
        flash(f'API Brawl Stars: HTTP {exc.code}. Confirma a tag, chave e IP autorizado.')
    except (URLError, TimeoutError, ValueError) as exc:
        flash(f'Não foi possível atualizar os troféus: {exc}')
    return redirect(url_for('bridge.home'), code=303)


def _submit(action):
    try:
        code = normalize_code(request.form.get('code', '')) if action == 'join' else None
        group_id = _enqueue(action, request.form.get('target', ''), code)
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for('bridge.home'), code=303)
    return redirect(url_for('bridge.job_page', group_id=group_id), code=303)


@bridge.post('/bridge/join')
def join():
    return _submit('join')


@bridge.post('/bridge/play')
def play():
    return _submit('play')


@bridge.post('/bridge/ai')
def ai():
    return _submit('ai')


@bridge.post('/bridge/snapshot')
def snapshot():
    return _submit('snapshot')


@bridge.get('/bridge/job/<group_id>')
def job_page(group_id):
    with _lock:
        group = _groups.get(group_id)
        if not group:
            return 'Ação desconhecida', 404
        title = {'join': 'Entrar na sala', 'play': 'Iniciar partida',
                 'ai': 'Teste de IA', 'snapshot': 'Capturar ecrã'}[group['action']]
        if group['code']:
            title += ' ' + group['code']
        result = _group_status(group)
    return render_template('job.html', title=title, group_id=group_id, result=result)


@bridge.get('/bridge/status/<group_id>')
def status(group_id):
    with _lock:
        group = _groups.get(group_id)
        if not group:
            return jsonify(error='unknown action'), 404
        for job_id in group['children']:
            job = _jobs[job_id]
            if job['status'] in ('queued', 'running') and time.time() - job['created'] > 120:
                job['status'], job['detail'] = 'failed', 'Tempo esgotado sem resposta do agente.'
        return jsonify(_group_status(group))


@bridge.get('/bridge/next')
def next_job():
    device = _agent()
    if not device:
        return jsonify(error='unauthorized'), 401
    _touch(device['id'])
    with _lock:
        queue = _pending[device['id']]
        while queue:
            job_id = queue.popleft()
            job = _jobs.get(job_id)
            if job and job['status'] == 'queued':
                job['status'] = 'running'
                return jsonify(id=job_id, action=job['action'], code=job.get('code'))
    return jsonify(job=None)


@bridge.post('/bridge/result/<job_id>')
def result(job_id):
    device = _agent()
    if not device:
        return jsonify(error='unauthorized'), 401
    data = request.get_json(silent=True) or {}
    if data.get('status') not in _TERMINAL:
        return jsonify(error='invalid status'), 400
    with _lock:
        job = _jobs.get(job_id)
        if not job or job['device_id'] != device['id']:
            return jsonify(error='unknown action'), 404
        job['status'] = data['status']
        job['detail'] = str(data.get('detail', ''))[:300]
    _touch(device['id'])
    return jsonify(ok=True)


@bridge.post('/bridge/screenshot-upload')
def upload_screenshot():
    device = _agent()
    if not device:
        return jsonify(error='unauthorized'), 401
    data = request.get_data(cache=False)
    if not (24 <= len(data) <= 12 * 1024 * 1024 and data[:8] == b'\x89PNG\r\n\x1a\n'
            and data[12:16] == b'IHDR'):
        return jsonify(error='invalid PNG'), 400
    path = _SCREENS / (device['id'] + '.png')
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)
    with _db() as con:
        con.execute('UPDATE devices SET screenshot_at=?,last_seen=? WHERE id=?',
                    (time.time(), time.time(), device['id']))
    return jsonify(ok=True)


@bridge.get('/bridge/device/<device_id>/screen')
def screen(device_id):
    if not _device(device_id):
        return 'Telemóvel desconhecido', 404
    path = _SCREENS / (device_id + '.png')
    if not path.exists():
        return 'Sem captura', 404
    response = send_file(io.BytesIO(path.read_bytes()), mimetype='image/png')
    response.headers['Cache-Control'] = 'no-store'
    return response


@bridge.get('/bridge/device/<device_id>/screen-page')
def screen_page(device_id):
    device = _device(device_id)
    if not device:
        return 'Telemóvel desconhecido', 404
    return render_template('screen.html', device=device)
