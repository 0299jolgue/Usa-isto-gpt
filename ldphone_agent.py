# Python 3.11+ / Termux on Android / Brawl Stars official app room agent
"""Open queued official room invitations in the installed game app."""

import json
import http.client
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import struct
import sys
import time
import csv
import io
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
    # Android's physical display metrics can remain portrait while the game is
    # rendered landscape. Input coordinates use the actual captured frame.
    deadline = time.monotonic() + 20
    width = height = 0
    while time.monotonic() < deadline:
        shot = subprocess.run(['su', '-c', '/system/bin/screencap -p'],
                              capture_output=True, timeout=5)
        if shot.returncode == 0:
            width, height = png_dimensions(shot.stdout)
            if width > height:
                break
        time.sleep(1)
    if width <= height:
        raise RuntimeError(f'O Brawl Stars ainda não apareceu na captura horizontal ({width}x{height})')
    x, y = round(width * .88), round(height * .88)
    tap = subprocess.run(['su', '-c', f'/system/bin/input tap {x} {y}'],
                         capture_output=True, text=True, timeout=15)
    if tap.returncode:
        raise RuntimeError((tap.stderr or tap.stdout).strip()[:200])
    return 'tapped', f'Toque em Jogar enviado em {x},{y} ({width}x{height}); confirma a partida no jogo.'


def png_dimensions(data):
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise RuntimeError('A captura do ecrã não é um PNG válido')
    width, height = struct.unpack('>II', data[16:24])
    if not (320 <= width <= 8192 and 180 <= height <= 8192):
        raise RuntimeError(f'Dimensões de captura inválidas: {width}x{height}')
    return width, height


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


def capture_screenshot(base, token, launch_game=True):
    if launch_game:
        launch = subprocess.run(['su', '-c', shlex.join([
            '/system/bin/monkey', '-p', PACKAGE, '-c',
            'android.intent.category.LAUNCHER', '1',
        ])], capture_output=True, timeout=15)
        if launch.returncode:
            raise RuntimeError('Não foi possível abrir o Brawl Stars para o print')
        time.sleep(1)
    shot = subprocess.run(['su', '-c', '/system/bin/screencap -p'],
                          capture_output=True, timeout=7)
    if shot.returncode:
        raise RuntimeError('Captura do ecrã falhou')
    width, height = png_dimensions(shot.stdout)
    connection = http.client.HTTPSConnection(urlparse(base).netloc, timeout=20)
    try:
        _ai_post(connection, '/bridge/screenshot-upload', token, shot.stdout, 'image/png')
        trophies = read_trophies(shot.stdout, width, height)
        if trophies is not None:
            _ai_post(connection, '/bridge/trophies-report', token,
                     json.dumps({'trophies': trophies}).encode(), 'application/json')
    finally:
        connection.close()
    return 'complete', f'Print guardado no painel ({width}x{height}).'


def run_ai(base, token, duration=20, stop_check=None, auto_start=True):
    host = urlparse(base).netloc
    connection = http.client.HTTPSConnection(host, timeout=120)
    frames = 0
    actions = 0
    cycles = []
    no_detection_since = time.monotonic()
    try:
        _ai_post(connection, '/ai/ready', token)
        if auto_start:
            start_match()
            time.sleep(6)
        else:
            launch = subprocess.run(['su', '-c', shlex.join([
                '/system/bin/monkey', '-p', PACKAGE, '-c',
                'android.intent.category.LAUNCHER', '1',
            ])], capture_output=True, timeout=15)
            if launch.returncode:
                raise RuntimeError('Não foi possível abrir o Brawl Stars')
            time.sleep(2)
        deadline = time.monotonic() + duration if duration is not None else None
        last_stop_check = 0
        connection.timeout = 20
        while deadline is None or time.monotonic() < deadline:
            if stop_check and time.monotonic() - last_stop_check > 2:
                last_stop_check = time.monotonic()
                if stop_check():
                    break
            begin = time.monotonic()
            shot = subprocess.run(['su', '-c', '/system/bin/screencap -p'],
                                  capture_output=True, timeout=5)
            if shot.returncode or not shot.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
                raise RuntimeError('Captura do ecrã falhou')
            data = _ai_post(connection, '/ai/step', token, shot.stdout, 'image/png')
            action = data['action']
            if data.get('state') != 'match' or data.get('detections', {}).get('player', 0):
                no_detection_since = time.monotonic()
            elif time.monotonic() - no_detection_since > 15:
                action = {'kind': 'tap', 'x1': round(data['width'] * .865),
                          'y1': round(data['height'] * .91)}
                no_detection_since = time.monotonic()
                print('Sem jogador detetado há 15 s; a tentar avançar o ecrã.', flush=True)
            if action['kind'] == 'tap':
                x, y = int(action['x1']), int(action['y1'])
                width, height = data['width'], data['height']
                if not (0 <= x < width and 0 <= y < height):
                    raise RuntimeError('Toque fora do ecrã')
                gesture = subprocess.run(['su', '-c', f'/system/bin/input tap {x} {y}'],
                                         capture_output=True, text=True, timeout=5)
                if gesture.returncode:
                    raise RuntimeError('Toque falhou: ' + gesture.stderr.strip()[:100])
                actions += 1
                time.sleep(2)
            elif action['kind'] in ('attack', 'move'):
                width, height = data['width'], data['height']
                coords = [int(action[key]) for key in ('x1', 'y1', 'x2', 'y2')]
                if not (0 <= coords[0] < width and 0 <= coords[2] < width and
                        0 <= coords[1] < height and 0 <= coords[3] < height):
                    raise RuntimeError('A IA devolveu coordenadas fora do ecrã')
                gesture_ms = max(80, min(500, int(action['duration_ms'])))
                command = ['/system/bin/input', 'touchscreen', 'swipe',
                           *(str(n) for n in coords), str(gesture_ms)]
                gesture = subprocess.run(['su', '-c', shlex.join(command)],
                                         capture_output=True, text=True, timeout=5)
                if gesture.returncode:
                    raise RuntimeError('Gesto falhou: ' + gesture.stderr.strip()[:100])
                actions += 1
            frames += 1
            elapsed = (time.monotonic() - begin) * 1000
            cycles.append(elapsed)
            print(f'IA frame={frames} estado={data.get("state", "?")} ação={action["kind"]} ciclo={elapsed:.0f}ms '
                  f'servidor={data["timings_ms"]["total"]}ms', flush=True)
    finally:
        connection.close()
    if not cycles:
        if stop_check:
            return 'complete', 'Parado antes da primeira imagem.'
        raise RuntimeError('Não foi analisada nenhuma imagem')
    ordered = sorted(cycles)
    median = ordered[len(ordered)//2]
    p90 = ordered[min(len(ordered)-1, int(len(ordered)*.9))]
    return 'complete', f'{frames} imagens, {actions} gestos; ciclo mediano {median:.0f} ms, P90 {p90:.0f} ms.'




def read_trophies(png, width, height):
    # On the home screen the account's total trophies sit beside the avatar,
    # near the top-left. Ignore other resource counters across the top bar.
    if not shutil.which('tesseract'):
        return None
    result = subprocess.run(['tesseract', 'stdin', 'stdout', 'tsv', '--psm', '11'],
                            input=png, capture_output=True, timeout=15)
    if result.returncode:
        return None
    candidates = []
    for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8', 'replace')), delimiter='\t'):
        value = re.sub(r'[^0-9]', '', row.get('text', ''))
        try:
            x, y, confidence = int(row['left']), int(row['top']), float(row['conf'])
        except (KeyError, ValueError):
            continue
        if value and 2 <= len(value) <= 6 and confidence >= 65 and 0 <= x < width * .32 \
                and height * .08 < y < height * .38:
            number = int(value)
            if number <= 1000000:
                candidates.append((confidence, number))
    return max(candidates)[1] if candidates else None

def tap_screen(base, token, coords):
    if not isinstance(coords, list) or len(coords) != 2 or any(
            not isinstance(n, (int, float)) or not 0 <= n <= 1 for n in coords):
        raise ValueError('Coordenadas inválidas')
    shot = subprocess.run(['su', '-c', '/system/bin/screencap -p'],
                          capture_output=True, timeout=7)
    width, height = png_dimensions(shot.stdout)
    x, y = round(coords[0] * width), round(coords[1] * height)
    result = subprocess.run(['su', '-c', f'/system/bin/input tap {x} {y}'],
                            capture_output=True, text=True, timeout=8)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:150])
    time.sleep(.8)
    capture_screenshot(base, token, launch_game=False)
    return 'complete', f'Toque em {x},{y}; novo print disponível.'


def run_farm(base, token, job_id):
    def stopped():
        return request_json(base, '/bridge/farm-state/' + job_id, token=token)['stop']
    status, detail = run_ai(base, token, duration=None, stop_check=stopped, auto_start=False)
    return status, 'Auto farm parado. ' + detail


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit('Uso: python ldphone_agent.py https://teu-site.shardweb.app CODIGO_DE_LIGACAO')
    base = sys.argv[1].rstrip('/')
    pair = sys.argv[2] if len(sys.argv) == 3 else ''
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
                registration = request_json(base, '/bridge/register', payload={'token': token, 'pair': pair})
                registered = True
                print('Agente ligado:', registration.get('name', 'LDPhone'), flush=True)
            job = request_json(base, '/bridge/next', token=token)
            if job.get('id') and job.get('action') in ('join', 'play', 'ai', 'snapshot', 'tap', 'farm'):
                print('A executar:', job['action'], job.get('code') or '', flush=True)
                try:
                    status, detail = (open_room(job['code']) if job['action'] == 'join'
                                      else run_ai(base, token) if job['action'] == 'ai'
                                      else capture_screenshot(base, token) if job['action'] == 'snapshot'
                                      else tap_screen(base, token, job['coords']) if job['action'] == 'tap'
                                      else run_farm(base, token, job['id']) if job['action'] == 'farm'
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
