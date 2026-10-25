# Python 3.11+ / Termux on Android / Brawl Stars official app room agent
"""Open queued official room invitations in the installed game app."""

import json
import hashlib
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PACKAGE = 'com.supercell.brawlstars'
TOKEN_FILE = Path.home() / '.brawl_room_agent_token'
CODE = re.compile(r'^X[QWERTYUPASDFGHJKLZCVBNM23456789]{2,12}$')
TCPDUMP = '/data/data/com.termux/files/usr/bin/tcpdump'


def request_json(base, path, token=None, payload=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    req = Request(base + path, data=body, headers=headers)
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def observe_join():
    if not Path(TCPDUMP).exists():
        return None
    command = [TCPDUMP, '-i', 'any', '-nn', '-s', '64', '-c', '1',
               'tcp dst port 9339 and tcp[((tcp[12] & 0xf0) >> 2):2] = 0x3816']
    return subprocess.Popen(['su', '-c', shlex.join(command)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def open_room(code):
    if not CODE.fullmatch(code):
        raise ValueError('invalid room code')
    url = f'https://link.brawlstars.com/invite/gameroom/pt?tag={code}'
    capture = observe_join()
    command = ['am', 'start', '-a', 'android.intent.action.VIEW', '-d', url, '-p', PACKAGE]
    action = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if action.returncode:
        if capture:
            capture.terminate()
        raise RuntimeError((action.stderr or action.stdout).strip()[:200])
    if capture:
        try:
            output, _ = capture.communicate(timeout=25)
            if capture.returncode == 0 and '9339' in output:
                return 'observed', 'Pedido de entrada 14358 observado na ligação do jogo.'
        except subprocess.TimeoutExpired:
            capture.terminate()
            capture.communicate(timeout=3)
    return 'sent', 'Convite aberto no Android; entrada ainda sem confirmação de rede.'


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Uso: python ldphone_agent.py https://teu-site.shardweb.app')
    base = sys.argv[1].rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path:
        raise SystemExit('Indica o endereço HTTPS do site, sem caminho no fim.')
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
        TOKEN_FILE.chmod(0o600)
    token = TOKEN_FILE.read_text().strip()
    pair_code = hashlib.blake2s(token.encode(), digest_size=4).hexdigest().upper()
    print('Código de emparelhamento:', pair_code, flush=True)
    registered = False
    while True:
        try:
            if not registered:
                request_json(base, '/bridge/register', payload={'token': token, 'pair_code': pair_code})
                registered = True
                print('Agente ligado. Deixa o Termux aberto.', flush=True)
            job = request_json(base, '/bridge/next', token=token)
            if job.get('id') and job.get('code'):
                print('A abrir sala:', job['code'], flush=True)
                try:
                    status, detail = open_room(job['code'])
                except Exception as exc:
                    status, detail = 'failed', f'{type(exc).__name__}: {exc}'
                request_json(base, '/bridge/result/' + job['id'], token=token,
                             payload={'status': status, 'detail': detail})
                print(detail, flush=True)
            time.sleep(2)
        except HTTPError as exc:
            if exc.code in (401, 404, 409):
                registered = False
            print('HTTP:', exc.code, flush=True)
            time.sleep(5)
        except (URLError, TimeoutError, OSError) as exc:
            print('Ligação:', exc, flush=True)
            time.sleep(5)


if __name__ == '__main__':
    main()
