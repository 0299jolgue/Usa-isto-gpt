# Python 3.11+ / Termux on Android / Brawl Stars official app room agent
"""Open queued official room invitations in the installed game app."""

import json
import http.client
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import time
from urllib.parse import urlparse

PACKAGE = 'com.supercell.brawlstars'
TOKEN_FILE = Path.home() / '.brawl_room_agent_token'
CODE = re.compile(r'^X[QWERTYUPASDFGHJKLZCVBNM23456789]{2,12}$')
TCPDUMP = '/data/data/com.termux/files/usr/bin/tcpdump'


class HttpStatus(Exception):
    def __init__(self, code, path, detail):
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__(f'HTTP {code} em {path}: {detail}')


def request_json(base, path, token=None, payload=None):
    command = ['curl', '-sS', '-m', '15', '-w', '\n%{http_code}',
               '-H', 'Accept: application/json']
    if token:
        command += ['-H', 'Authorization: Bearer ' + token]
    body = None
    if payload is not None:
        body = json.dumps(payload)
        command += ['-H', 'Content-Type: application/json', '-X', 'POST', '--data-binary', '@-']
    command.append(base + path)
    result = subprocess.run(command, input=body, capture_output=True, text=True, timeout=18)
    if result.returncode:
        raise OSError(f'curl: {result.stderr.strip()[:120]}')
    response, separator, status = result.stdout.rpartition('\n')
    if not separator or not status.isdecimal():
        raise ValueError(f'Resposta HTTP inválida em {path}')
    if int(status) >= 400:
        raise HttpStatus(int(status), path, response.strip()[:120])
    return json.loads(response)


def observe_join():
    if not Path(TCPDUMP).exists():
        return None
    command = [TCPDUMP, '-i', 'any', '-nn', '-s', '128', '-c', '1',
               'tcp dst port 9339 and tcp[((tcp[12] & 0xf0) >> 2):2] = 0x3816']
    return subprocess.Popen(['su', '-c', shlex.join(command)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def open_room(code):
    if not CODE.fullmatch(code):
        raise ValueError('invalid room code')
    url = f'https://link.brawlstars.com/invite/gameroom/pt?tag={code}'
    capture = observe_join()
    command = ['/system/bin/am', 'start', '-W', '-a', 'android.intent.action.VIEW',
               '-c', 'android.intent.category.BROWSABLE', '-d', url, '-p', PACKAGE]
    action = subprocess.run(['su', '-c', shlex.join(command)], capture_output=True, text=True, timeout=45)
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


def start_match():
    # The official game is the TCP client; the agent only presses its Play button.
    launch = subprocess.run(['su', '-c', shlex.join([
        '/system/bin/monkey', '-p', PACKAGE, '-c',
        'android.intent.category.LAUNCHER', '1',
    ])], capture_output=True, text=True, timeout=30)
    if launch.returncode:
        raise RuntimeError((launch.stderr or launch.stdout).strip()[:200])
    time.sleep(4)
    foreground = subprocess.run(['su', '-c', 'dumpsys activity activities'],
                                capture_output=True, text=True, timeout=15)
    if foreground.returncode or not re.search(r'(?:topResumedActivity|mResumedActivity).*com\.supercell\.brawlstars',
                                               foreground.stdout):
        raise RuntimeError('Brawl Stars não está em primeiro plano')
    display = subprocess.run(['su', '-c', 'dumpsys display'],
                             capture_output=True, text=True, timeout=15)
    dimensions = re.search(r'logicalWidth=(\d+).*?logicalHeight=(\d+)', display.stdout)
    if not dimensions:
        dimensions = re.search(r'(?:(?:mBase|mOverride)?DisplayInfo=DisplayInfo\{)[^\n]*?\b(\d+) x (\d+)\b',
                               display.stdout)
    if display.returncode or not dimensions:
        raise RuntimeError('Não foi possível determinar o tamanho do ecrã')
    width, height = map(int, dimensions.groups())
    if width <= height or width < 500 or height < 300:
        raise RuntimeError(f'O jogo não está em modo horizontal ({width}x{height})')
    x, y = round(width * .88), round(height * .88)
    tap = subprocess.run(['su', '-c', f'/system/bin/input tap {x} {y}'],
                         capture_output=True, text=True, timeout=15)
    if tap.returncode:
        raise RuntimeError((tap.stderr or tap.stdout).strip()[:200])
    return 'tapped', f'Toque em Jogar enviado em {x},{y} ({width}x{height}); confirma a partida no jogo.'


def _ai_post(connection, path, token, body=b'', content_type='application/octet-stream'):
    connection.request('POST', path, body=body,
                       headers={'Authorization': 'Bearer ' + token,
                                'Content-Type': content_type,
                                'Content-Length': str(len(body))})
    response = connection.getresponse()
    raw = response.read()
    if response.status >= 400:
        raise RuntimeError(f'{path}: HTTP {response.status}: {raw[:160].decode("utf-8", "replace")}')
    return json.loads(raw)


def run_ai(base, token):
    host = urlparse(base).netloc
    connection = http.client.HTTPSConnection(host, timeout=120)
    frames = 0
    actions = 0
    cycles = []
    try:
        _ai_post(connection, '/ai/ready', token)
        start_match()
        time.sleep(6)
        deadline = time.monotonic() + 20
        connection.timeout = 15
        while time.monotonic() < deadline:
            begin = time.monotonic()
            shot = subprocess.run(['su', '-c', '/system/bin/screencap -p'],
                                  capture_output=True, timeout=5)
            if shot.returncode or not shot.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
                raise RuntimeError('Captura do ecrã falhou')
            data = _ai_post(connection, '/ai/step', token, shot.stdout, 'image/png')
            action = data['action']
            if action['kind'] in ('attack', 'move'):
                width, height = data['width'], data['height']
                coords = [int(action[key]) for key in ('x1', 'y1', 'x2', 'y2')]
                if not (0 <= coords[0] < width and 0 <= coords[2] < width and
                        0 <= coords[1] < height and 0 <= coords[3] < height):
                    raise RuntimeError('A IA devolveu coordenadas fora do ecrã')
                duration = max(80, min(250, int(action['duration_ms'])))
                command = ['/system/bin/input', 'touchscreen', 'swipe',
                           *(str(n) for n in coords), str(duration)]
                gesture = subprocess.run(['su', '-c', shlex.join(command)],
                                         capture_output=True, text=True, timeout=5)
                if gesture.returncode:
                    raise RuntimeError('Gesto falhou: ' + gesture.stderr.strip()[:100])
                actions += 1
            frames += 1
            elapsed = (time.monotonic() - begin) * 1000
            cycles.append(elapsed)
            print(f'IA frame={frames} ação={action["kind"]} ciclo={elapsed:.0f}ms '
                  f'servidor={data["timings_ms"]["total"]}ms', flush=True)
    finally:
        connection.close()
    if not cycles:
        raise RuntimeError('Não foi analisada nenhuma imagem')
    ordered = sorted(cycles)
    median = ordered[len(ordered)//2]
    p90 = ordered[min(len(ordered)-1, int(len(ordered)*.9))]
    return 'complete', f'{frames} imagens, {actions} gestos; ciclo mediano {median:.0f} ms, P90 {p90:.0f} ms.'


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
    registered = False
    while True:
        try:
            if not registered:
                request_json(base, '/bridge/register', payload={'token': token})
                registered = True
                print('Agente ligado. Deixa o Termux aberto.', flush=True)
            job = request_json(base, '/bridge/next', token=token)
            if job.get('id') and job.get('action') in ('join', 'play', 'ai'):
                print('A executar:', job['action'], job.get('code') or '', flush=True)
                try:
                    status, detail = (open_room(job['code']) if job['action'] == 'join'
                                      else run_ai(base, token) if job['action'] == 'ai'
                                      else start_match())
                except Exception as exc:
                    status, detail = 'failed', f'{type(exc).__name__}: {exc}'
                for attempt in range(5):
                    try:
                        request_json(base, '/bridge/result/' + job['id'], token=token,
                                     payload={'status': status, 'detail': detail})
                        break
                    except (HttpStatus, TimeoutError, OSError, ValueError):
                        if attempt == 4:
                            print('Falha ao enviar o resultado ao site.', flush=True)
                        else:
                            time.sleep(2)
                print(detail, flush=True)
            time.sleep(2)
        except HttpStatus as exc:
            if exc.code in (401, 404, 409):
                registered = False
            print(exc, flush=True)
            time.sleep(5)
        except (TimeoutError, OSError, ValueError) as exc:
            print('Ligação:', exc, flush=True)
            time.sleep(5)


if __name__ == '__main__':
    main()
