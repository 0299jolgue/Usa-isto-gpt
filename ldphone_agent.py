# Python 3.11+ / Termux on Android / Brawl Stars official app room agent
"""Open queued official room invitations in the installed game app."""

import json
import http.client
import os
from pathlib import Path
import re
import secrets
import random
import shlex
import shutil
import subprocess
import struct
import sys
import time
import threading
import csv
import io
import fcntl
import select
from array import array
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


def _ai_post(connection, path, token, body=b'', content_type='application/octet-stream', extra_headers=None):
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': content_type,
               'Content-Length': str(len(body))}
    if extra_headers:
        headers.update(extra_headers)
    connection.request('POST', path, body=body, headers=headers)
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


def swipe_action(action, width, height):
    coords = [int(action[key]) for key in ('x1', 'y1', 'x2', 'y2')]
    if not (0 <= coords[0] < width and 0 <= coords[2] < width and
            0 <= coords[1] < height and 0 <= coords[3] < height):
        raise RuntimeError('A IA devolveu coordenadas fora do ecrã')
    duration_ms = max(80, min(2200, int(action['duration_ms'])))
    command = ['/system/bin/input', 'touchscreen', 'swipe',
               *(str(n) for n in coords), str(duration_ms)]
    gesture = subprocess.run(['su', '-c', shlex.join(command)],
                             capture_output=True, text=True, timeout=5)
    if gesture.returncode:
        raise RuntimeError('Gesto falhou: ' + gesture.stderr.strip()[:100])


def find_exit_button(png, width, height):
    if not shutil.which('tesseract'):
        return None
    # The spectator screen uses a smaller button than the results screen.
    for page_mode in ('11', '6'):
        try:
            result = subprocess.run(['tesseract', 'stdin', 'stdout', 'tsv', '--psm', page_mode],
                                    input=png, capture_output=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode:
            continue
        for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8', 'replace')), delimiter='\t'):
            word = re.sub(r'[^A-Z]', '', row.get('text', '').upper())
            if word not in ('SAIR', 'EXIT', 'SALIR'):
                continue
            try:
                x, y = int(row['left']), int(row['top'])
                w, h = int(row['width']), int(row['height'])
                confidence = float(row['conf'])
            except (KeyError, ValueError):
                continue
            cx, cy = x + w // 2, y + h // 2
            if confidence >= 35 and width * .1 < cx < width and height * .35 < cy < height:
                return cx, cy
    return None


import fcntl
import select
from array import array

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, BTN_TOUCH = 0, 330
ABS_MT_SLOT, ABS_MT_TRACKING_ID = 47, 57
ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 53, 54
ABS_MT_TOUCH_MAJOR, ABS_MT_PRESSURE = 48, 58


def _abs_range(fd, code):
    # EVIOCGABS(code), returning struct input_absinfo.
    request = (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + code)
    data = array('i', [0] * 6)
    fcntl.ioctl(fd, request, data, True)
    return data[1], data[2]


def _touch_device():
    candidates = []
    for path in sorted(Path('/dev/input').glob('event*')):
        fd = None
        try:
            fd = os.open(path, os.O_RDWR)
            xlo, xhi = _abs_range(fd, ABS_MT_POSITION_X)
            ylo, yhi = _abs_range(fd, ABS_MT_POSITION_Y)
            _, slots = _abs_range(fd, ABS_MT_SLOT)
            if xhi > xlo and yhi > ylo and slots >= 1:
                candidates.append(((xhi-xlo)*(yhi-ylo), fd, str(path), (xlo,xhi,ylo,yhi)))
            else:
                os.close(fd)
        except (OSError, ValueError):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
    if not candidates:
        raise RuntimeError('Nenhum ecrã multitouch encontrado em /dev/input')
    candidates.sort(reverse=True)
    _, fd, path, bounds = candidates.pop(0)
    for _, other_fd, _, _ in candidates:
        os.close(other_fd)
    return fd, path, bounds


def _screen_rotation():
    result = subprocess.run(['/system/bin/dumpsys', 'input'], capture_output=True,
                            text=True, timeout=8)
    match = re.search(r'SurfaceOrientation:\s*([0-3])', result.stdout)
    if not match:
        match = re.search(r'(?:mCurrentOrientation|mRotation|rotation)=([0-3])', result.stdout)
    return int(match.group(1)) if match else 0


def _map_touch(x, y, width, height, bounds, rotation):
    sx, sy = max(0, min(1, x / width)), max(0, min(1, y / height))
    if rotation == 1:
        sx, sy = 1-sy, sx
    elif rotation == 2:
        sx, sy = 1-sx, 1-sy
    elif rotation == 3:
        sx, sy = sy, 1-sx
    xlo, xhi, ylo, yhi = bounds
    return round(xlo + sx*(xhi-xlo)), round(ylo + sy*(yhi-ylo))


def _ev(event_type, code, value):
    return struct.pack('llHHi', 0, 0, event_type, code, value)


def touch_helper():
    fd, path, bounds = _touch_device()
    rotation = _screen_rotation()
    fingers = set()
    tracking = 1
    print(json.dumps({'ready': True, 'device': path, 'rotation': rotation}), flush=True)

    def emit(events):
        payload = b''.join(_ev(*event) for event in events)
        while payload:
            payload = payload[os.write(fd, payload):]

    def release(slot):
        if slot not in fingers:
            return
        fingers.remove(slot)
        events = [(EV_ABS, ABS_MT_SLOT, slot), (EV_ABS, ABS_MT_TRACKING_ID, -1)]
        if not fingers:
            events.append((EV_KEY, BTN_TOUCH, 0))
        events.append((EV_SYN, SYN_REPORT, 0))
        emit(events)

    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
                op = command['op']
                if op == 'reset':
                    for slot in tuple(fingers):
                        release(slot)
                elif op == 'up':
                    release(int(command['slot']))
                elif op in ('down', 'move'):
                    slot = int(command['slot'])
                    if slot not in (0, 1):
                        raise ValueError('slot inválido')
                    tx, ty = _map_touch(float(command['x']), float(command['y']),
                                        int(command['width']), int(command['height']),
                                        bounds, rotation)
                    events = [(EV_ABS, ABS_MT_SLOT, slot)]
                    if slot not in fingers:
                        events.append((EV_ABS, ABS_MT_TRACKING_ID, tracking))
                        tracking += 1
                        fingers.add(slot)
                        if len(fingers) == 1:
                            events.append((EV_KEY, BTN_TOUCH, 1))
                    events += [(EV_ABS, ABS_MT_POSITION_X, tx),
                               (EV_ABS, ABS_MT_POSITION_Y, ty),
                               (EV_SYN, SYN_REPORT, 0)]
                    emit(events)
                else:
                    raise ValueError('operação inválida')
                print('ok', flush=True)
            except Exception as exc:
                print('error:' + str(exc), flush=True)
    finally:
        for slot in tuple(fingers):
            release(slot)
        os.close(fd)


class TouchController:
    def __init__(self):
        command = [sys.executable, str(Path(__file__).resolve()), '--touch-helper']
        self.process = subprocess.Popen(['su', '-c', shlex.join(command)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)
        if not select.select([self.process.stdout], [], [], 8)[0]:
            self.close()
            raise RuntimeError('O controlador multitouch não iniciou')
        line = self.process.stdout.readline()
        try:
            ready = json.loads(line)
        except ValueError as exc:
            self.close()
            raise RuntimeError('Resposta inválida do multitouch: ' + line[:100]) from exc
        if not ready.get('ready'):
            self.close()
            raise RuntimeError('O controlador multitouch falhou')
        self.moving = False
        print('Multitouch:', ready['device'], 'rotação', ready['rotation'], flush=True)

    def send(self, op, slot=None, point=None, size=None):
        payload = {'op': op}
        if slot is not None:
            payload['slot'] = slot
        if point is not None:
            payload.update(x=point[0], y=point[1], width=size[0], height=size[1])
        self.process.stdin.write(json.dumps(payload) + '\n')
        self.process.stdin.flush()
        if not select.select([self.process.stdout], [], [], 3)[0]:
            raise RuntimeError('O multitouch não respondeu')
        response = self.process.stdout.readline().strip()
        if response != 'ok':
            raise RuntimeError('Multitouch: ' + response[:150])

    def move(self, action, width, height):
        start = (int(action['x1']), int(action['y1']))
        end = (int(action['x2']), int(action['y2']))
        if not self.moving:
            self.send('down', 0, start, (width, height))
            self.moving = True
        self.send('move', 0, end, (width, height))

    def release_move(self):
        if self.moving:
            self.send('up', 0)
            self.moving = False

    def attack(self, action, width, height):
        start = (int(action['x1']), int(action['y1']))
        end = (int(action['x2']), int(action['y2']))
        self.send('down', 1, start, (width, height))
        try:
            self.send('move', 1, end, (width, height))
            time.sleep(max(.08, min(.35, int(action['duration_ms'])/1000)))
        finally:
            self.send('up', 1)

    def tap(self, x, y, width, height):
        self.release_move()
        self.send('down', 1, (x, y), (width, height))
        time.sleep(.06)
        self.send('up', 1)

    def auto_fire(self, x, y, width, height):
        # Slot 0 keeps steering while slot 1 taps the game's auto-aim button.
        self.send('down', 1, (x, y), (width, height))
        try:
            time.sleep(.06)
        finally:
            self.send('up', 1)

    def close(self):
        try:
            if self.process.poll() is None and self.process.stdin:
                self.process.stdin.write('{"op":"reset"}\n')
                self.process.stdin.flush()
                self.process.stdin.close()
                self.process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()
        for stream in (self.process.stdout, self.process.stderr):
            if stream:
                stream.close()


def choose_post_frame_action(action, state, player_seen, no_player_seconds,
                             exit_button, width, height):
    if exit_button:
        return {'kind': 'tap', 'x1': exit_button[0], 'y1': exit_button[1],
                'reason': 'exit_button'}
    if state == 'match' and not player_seen and no_player_seconds > 20 \
            and action['kind'] != 'tap':
        return {'kind': 'tap', 'x1': round(width * .865),
                'y1': round(height * .91), 'reason': 'stuck_screen'}
    return action


def report_learning(base, token, stats):
    try:
        request_json(base, '/bridge/learning-report', token=token, payload=stats)
    except (OSError, TimeoutError, ValueError, HttpStatus) as exc:
        print('Estatísticas por enviar:', exc, flush=True)


class TacticsMemory:
    """Small on-device bandit: retain wins/losses per movement policy."""
    FILE = Path.home() / '.brawl_room_tactics.json'
    NAMES = ('aggressive', 'balanced', 'cautious')

    def __init__(self):
        try:
            stored = json.loads(self.FILE.read_text())
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        self.stats = {}
        for name in self.NAMES:
            row = stored.get(name, {})
            if not isinstance(row, dict):
                row = {}
            clean = {}
            for key in ('wins', 'losses'):
                try:
                    value = float(row.get(key, 0))
                    clean[key] = value if 0 <= value <= 100000 else 0.0
                except (TypeError, ValueError):
                    clean[key] = 0.0
            self.stats[name] = clean
        self.current = self.choose()

    def choose(self):
        return max(self.NAMES, key=lambda name: random.betavariate(
            self.stats[name]['wins'] + 1, self.stats[name]['losses'] + 1))

    def record(self, result):
        if result not in ('win', 'loss', 'draw'):
            return
        row = self.stats[self.current]
        row['wins'] += 1 if result == 'win' else .5 if result == 'draw' else 0
        row['losses'] += 1 if result == 'loss' else .5 if result == 'draw' else 0
        temporary = self.FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.stats, separators=(',', ':')))
        temporary.replace(self.FILE)
        previous = self.current
        self.current = self.choose()
        print(f'Aprendizagem: {previous} resultado={result}; próxima tática={self.current}; '
              f'estatísticas={self.stats}', flush=True)


def run_ai(base, token, duration=20, stop_check=None, auto_start=True):
    host = urlparse(base).netloc
    connection = http.client.HTTPSConnection(host, timeout=120)
    frames = 0
    actions = 0
    cycles = []
    touch = None
    no_detection_since = time.monotonic()
    last_exit_scan = 0
    step_errors = 0
    learner = TacticsMemory() if duration is None else None
    in_match = False
    awaiting_new_match = False
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
        try:
            touch = TouchController()
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print('Multitouch indisponível; a usar gestos longos:', exc, flush=True)
        deadline = time.monotonic() + duration if duration is not None else None
        last_stop_check = 0
        connection.timeout = 20
        if connection.sock:
            connection.sock.settimeout(20)
        while deadline is None or time.monotonic() < deadline:
            if stop_check and time.monotonic() - last_stop_check > 2:
                last_stop_check = time.monotonic()
                if stop_check():
                    break
            begin = time.monotonic()
            try:
                shot = subprocess.run(['su', '-c', '/system/bin/screencap -p'],
                                      capture_output=True, timeout=7)
                if shot.returncode or not shot.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise RuntimeError('Captura do ecrã falhou')
                data = _ai_post(connection, '/ai/step', token, shot.stdout, 'image/png',
                                extra_headers={'X-Strategy': learner.current if learner else 'balanced'})
                step_errors = 0
            except (OSError, TimeoutError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                if 'HTTP 401' in str(exc) or 'HTTP 403' in str(exc):
                    raise
                step_errors += 1
                if touch:
                    try:
                        touch.release_move()
                    except (OSError, RuntimeError) as touch_exc:
                        print('Multitouch falhou:', touch_exc, flush=True)
                        touch.close()
                        touch = None
                print(f'IA falha temporária {step_errors}/4: {exc}', flush=True)
                connection.close()
                connection = http.client.HTTPSConnection(host, timeout=20)
                if step_errors >= 4:
                    raise RuntimeError(f'IA parou após quatro falhas seguidas: {exc}') from exc
                time.sleep(1)
                continue
            action = data['action']
            state = data.get('state', 'match')
            player_seen = bool(data.get('detections', {}).get('player', 0))
            no_player_seconds = time.monotonic() - no_detection_since
            exit_button = None
            # Spectator mode can still show another brawler, so player_seen is
            # not reliable evidence that our account is alive.
            scan_interval = 3 if state.startswith('end') or not player_seen else 8
            if state.startswith('end') or state == 'match':
                should_scan_exit = time.monotonic() - last_exit_scan > scan_interval
            else:
                should_scan_exit = False
            if should_scan_exit:
                last_exit_scan = time.monotonic()
                exit_button = find_exit_button(shot.stdout, data['width'], data['height'])
                if exit_button:
                    print(f'Botão Sair encontrado em {exit_button}.', flush=True)
            action = choose_post_frame_action(action, state, player_seen, no_player_seconds,
                                              exit_button, data['width'], data['height'])
            if learner:
                if state in ('lobby', 'match_making'):
                    awaiting_new_match = False
                if state == 'match' and player_seen and not awaiting_new_match:
                    in_match = True
                result = ('win' if state in ('end_victory', 'end_place_1') else
                          'loss' if state.startswith('end_') and state != 'end_draw' else
                          'draw' if state == 'end_draw' else
                          'loss' if action.get('reason') == 'exit_button' and in_match else None)
                if in_match and result:
                    learner.record(result)
                    stats_snapshot = json.loads(json.dumps(learner.stats))
                    threading.Thread(target=report_learning,
                                     args=(base, token, stats_snapshot), daemon=True).start()
                    in_match = False
                    awaiting_new_match = True
            if state != 'match' or player_seen or action.get('reason') == 'stuck_screen':
                no_detection_since = time.monotonic()
            movement = data.get('movement') if action['kind'] != 'tap' and state == 'match' else None
            if movement:
                if touch:
                    try:
                        touch.move(movement, data['width'], data['height'])
                    except (OSError, RuntimeError) as exc:
                        print('Multitouch falhou; gesto longo:', exc, flush=True)
                        touch.close()
                        touch = None
                if not touch:
                    long_move = dict(movement, duration_ms=1500)
                    swipe_action(long_move, data['width'], data['height'])
                actions += 1
            elif touch:
                try:
                    touch.release_move()
                except (OSError, RuntimeError) as exc:
                    print('Multitouch falhou:', exc, flush=True)
                    touch.close()
                    touch = None
            if action['kind'] == 'tap':
                x, y = int(action['x1']), int(action['y1'])
                width, height = data['width'], data['height']
                if not (0 <= x < width and 0 <= y < height):
                    raise RuntimeError('Toque fora do ecrã')
                if touch:
                    try:
                        touch.release_move()
                    except (OSError, RuntimeError) as exc:
                        print('Multitouch falhou; toque normal:', exc, flush=True)
                        touch.close()
                        touch = None
                gesture = subprocess.run(['su', '-c', f'/system/bin/input tap {x} {y}'],
                                         capture_output=True, text=True, timeout=5)
                if gesture.returncode:
                    raise RuntimeError('Toque falhou: ' + gesture.stderr.strip()[:100])
                actions += 1
                time.sleep(2.5 if action.get('reason') == 'exit_button' else 1.5)
            elif action['kind'] == 'auto_fire':
                x, y = int(action['x1']), int(action['y1'])
                if touch:
                    try:
                        touch.auto_fire(x, y, data['width'], data['height'])
                    except (OSError, RuntimeError) as exc:
                        print('Multitouch falhou; auto fire normal:', exc, flush=True)
                        touch.close()
                        touch = None
                if not touch:
                    gesture = subprocess.run(['su', '-c', f'/system/bin/input tap {x} {y}'],
                                             capture_output=True, text=True, timeout=5)
                    if gesture.returncode:
                        raise RuntimeError('Auto fire falhou: ' + gesture.stderr.strip()[:100])
                actions += 1
            elif action['kind'] == 'attack':
                if touch:
                    try:
                        touch.attack(action, data['width'], data['height'])
                    except (OSError, RuntimeError) as exc:
                        print('Multitouch falhou; ataque normal:', exc, flush=True)
                        touch.close()
                        touch = None
                if not touch:
                    swipe_action(action, data['width'], data['height'])
                actions += 1
            elif action['kind'] == 'move' and not movement:
                if touch:
                    touch.move(action, data['width'], data['height'])
                else:
                    swipe_action(dict(action, duration_ms=1500), data['width'], data['height'])
                actions += 1
            frames += 1
            elapsed = (time.monotonic() - begin) * 1000
            cycles.append(elapsed)
            print(f'IA frame={frames} estado={state} movimento={bool(data.get("movement"))} ação={action["kind"]} ciclo={elapsed:.0f}ms '
                  f'servidor={data["timings_ms"]["total"]}ms', flush=True)
    finally:
        if touch:
            touch.close()
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
            if exc.code == 403 and exc.path == '/bridge/register':
                raise SystemExit('Código de ligação inválido. Atualiza o painel no navegador e executa o novo comando.')
            if exc.code in (401, 404, 409):
                registered = False
            print(exc, flush=True)
            time.sleep(5)
        except (TimeoutError, OSError, ValueError) as exc:
            print('Ligação:', exc, flush=True)
            time.sleep(5)


if __name__ == '__main__':
    if sys.argv[1:] == ['--touch-helper']:
        touch_helper()
    else:
        main()
