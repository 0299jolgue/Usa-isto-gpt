# Python 3.12 / ShardCloud Linux / PylaAI ONNX vision policy
"""Fast, single-frame enemy detection and a small Brawl Stars control policy."""

import hashlib
import logging
import math
import os
from pathlib import Path
import threading
import time
from urllib.request import urlopen

log = logging.getLogger('brawl-room.ai')
MODEL_SHA256 = 'e9e2394ab3b65c92b88334a4ecc6675c054ee717c5fea9f35ad8f111ba13a9a4'
MODEL_URL = ('https://raw.githubusercontent.com/PylaAI/PylaAI/'
             '284714d262b4c8a583e1fb0f34ef021b153d29e2/models/mainInGameModel.onnx')
MODEL_PATH = Path(os.environ.get('PYLA_MODEL_PATH', '/tmp/pyla-mainInGameModel.onnx'))
_lock = threading.Lock()
_session = None
_contexts = {}


def _context(device_id):
    if not device_id:
        return {'max_health_pixels': 0, 'last_health': None, 'dodge_until': 0,
                'last_super': 0, 'patrol_since': time.monotonic(), 'patrol_step': 0,
                'last_target': None, 'last_enemy_seen': 0, 'last_move': None,
                'last_player_seen': 0}
    now = time.monotonic()
    with _lock:
        for key, value in list(_contexts.items()):
            if now - value['seen'] > 1800:
                del _contexts[key]
        return _contexts.setdefault(device_id, {
            'max_health_pixels': 0, 'last_health': None,
            'dodge_until': 0, 'last_super': 0, 'patrol_since': now,
            'patrol_step': 0, 'last_target': None, 'last_enemy_seen': 0,
            'last_move': None, 'last_player_seen': 0, 'seen': now,
        })


def _super_ready(frame):
    """PylaAI's yellow-pixel check, scaled from its 1920x1080 crop."""
    import cv2
    h, w = frame.shape[:2]
    x1, x2 = round(w*1460/1920), round(w*1560/1920)
    y1, y2 = round(h*830/1080), round(h*930/1080)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return False
    yellow = cv2.inRange(cv2.cvtColor(roi, cv2.COLOR_BGR2HSV),
                         (17, 170, 200), (27, 255, 255))
    return cv2.countNonZero(yellow) > (1800 * (w/1920) * (h/1080))


def _health_pixels(frame, player):
    """Measure the bright green fill immediately above the detected player."""
    import cv2
    h, w = frame.shape[:2]
    cx, cy, _, _, box_h = player
    radius = max(12, round(w * .055))
    x1, x2 = max(0, round(cx)-radius), min(w, round(cx)+radius)
    y1 = max(0, round(cy-box_h*.95))
    y2 = max(y1, min(h, round(cy-box_h*.25)))
    if x2 <= x1 or y2 <= y1:
        return 0
    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (35, 90, 80), (88, 255, 255))
    row_widths = (green > 0).sum(axis=1)
    return int(row_widths.max()) if row_widths.size else 0


def _power_boxes(frame, player):
    """Conservative color and shape candidates for Showdown power-cube crates."""
    import cv2
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, (7, 95, 85), (32, 255, 255))
    gold[:round(h*.08)] = 0
    gold[round(h*.82):] = 0
    gold[:, :round(w*.12)] = 0
    gold[:, round(w*.88):] = 0
    gold = cv2.morphologyEx(gold, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    contours, _ = cv2.findContours(gold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (w*.018 <= bw <= w*.11 and h*.03 <= bh <= h*.18 and .55 <= bw/bh <= 1.8):
            continue
        if cv2.contourArea(contour) / (bw*bh) < .38:
            continue
        # Power-cube crates have a short green health bar above them.
        bar = hsv[max(0,y-round(h*.035)):y, x:x+bw]
        if bar.size == 0:
            continue
        green = cv2.inRange(bar, (35, 90, 80), (88, 255, 255))
        if (green > 0).sum(axis=1).max(initial=0) < bw*.25:
            continue
        center = (x+bw/2, y+bh/2)
        if math.hypot(center[0]-player[0], center[1]-player[1]) > w*.45:
            continue
        boxes.append(center)
    return boxes


def _model_file():
    if MODEL_PATH.exists() and hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == MODEL_SHA256:
        return MODEL_PATH
    with urlopen(MODEL_URL, timeout=60) as response:
        data = response.read(16_000_001)
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise RuntimeError('O modelo PylaAI transferido não passou na verificação SHA-256')
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_PATH.with_suffix('.tmp')
    temporary.write_bytes(data)
    temporary.replace(MODEL_PATH)
    return MODEL_PATH


def ready():
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = min(4, os.cpu_count() or 1)
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _session = ort.InferenceSession(str(_model_file()), sess_options=options,
                                            providers=['CPUExecutionProvider'])
            log.info('model_ready path=%s', MODEL_PATH)
    return _session


def decide(png, strategy='balanced', device_id=None, mode=None, brawler=None):
    import cv2
    import numpy as np
    started = time.perf_counter()
    frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('Captura PNG inválida')
    height, width = frame.shape[:2]
    if not (320 <= width <= 8192 and 180 <= height <= 8192):
        raise ValueError('Dimensões da captura inválidas')
    decoded = time.perf_counter()
    from pyla_state import classify
    state, state_confidence = classify(frame)
    if state != 'match':
        if device_id:
            with _lock:
                _contexts.pop(device_id, None)
        position = ((.865, .91) if state.startswith('end') or state == 'trophy_reward'
                    else (.88, .88) if state == 'lobby' else None)
        action = ({'kind': 'tap', 'x1': round(position[0] * width),
                   'y1': round(position[1] * height)}
                  if position else {'kind': 'none'})
        return {'action': action, 'state': state, 'state_confidence': state_confidence,
                'width': width, 'height': height, 'detections': {},
                'timings_ms': {'decode': round((decoded-started)*1000, 1),
                               'inference': 0, 'total': round((time.perf_counter()-started)*1000, 1)}}
    # Match Pyla's top-left letterbox preprocessing, including its gray padding.
    scale = min(640 / width, 640 / height)
    resized_w, resized_h = int(width * scale), int(height * scale)
    resized = cv2.cvtColor(cv2.resize(frame, (resized_w, resized_h)), cv2.COLOR_BGR2RGB)
    tensor = np.full((1, 3, 640, 640), 128.0 / 255.0, dtype=np.float32)
    tensor[0, :, :resized_h, :resized_w] = resized.transpose(2, 0, 1) / 255.0
    session = ready()
    raw = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
    inferred = time.perf_counter()
    scores = raw[4:]
    classes = scores.argmax(axis=0)
    confidence = scores[classes, np.arange(scores.shape[1])]
    # Pyla's model has enemy (0), teammate (1), and player (2).
    found = {}
    for class_id, label in ((2, 'player'), (0, 'enemy')):
        indices = np.flatnonzero((classes == class_id) & (confidence >= .55))
        indices = indices[np.argsort(confidence[indices])[-16:]]
        found[label] = [(float(raw[0, i] * width / resized_w), float(raw[1, i] * height / resized_h),
                         float(confidence[i]), float(raw[2, i] * width / resized_w),
                         float(raw[3, i] * height / resized_h)) for i in indices]
    player = max(found['player'], key=lambda row: row[2], default=None)
    # YOLO often returns several overlapping boxes for one character.
    enemies = []
    for row in sorted(found['enemy'], key=lambda item: item[2], reverse=True):
        if all((row[0]-other[0])**2 + (row[1]-other[1])**2 > (width*.045)**2
               for other in enemies):
            enemies.append(row)
    def clamp_x(value): return max(0, min(width-1, round(value)))
    def clamp_y(value): return max(0, min(height-1, round(value)))
    tactics = {
        'aggressive': {'range': .13, 'attack_ms': 180, 'auto_fire_range': .13},
        'balanced': {'range': .16, 'attack_ms': 130, 'auto_fire_range': .12},
        'cautious': {'range': .21, 'attack_ms': 100, 'auto_fire_range': .11},
    }.get(strategy, {'range': .16, 'attack_ms': 130, 'auto_fire_range': .12})
    context = _context(device_id)
    if device_id:
        context['seen'] = time.monotonic()
    if enemies:
        context['last_target'] = enemies[0]
        context['last_enemy_seen'] = time.monotonic()
    elif player and context['last_target'] and \
            time.monotonic()-context['last_enemy_seen'] < .9:
        remembered = context['last_target']
        if math.hypot(remembered[0]-player[0], remembered[1]-player[1]) < width*.30:
            enemies = [remembered]
    movement = None
    health = None
    tactic = 'patrol'
    if player:
        context['last_player_seen'] = time.monotonic()
        green_pixels = _health_pixels(frame, player)
        if green_pixels >= max(8, width*.012):
            context['max_health_pixels'] = max(context['max_health_pixels'], green_pixels)
            health = min(1., green_pixels / context['max_health_pixels'])
        previous_health = context['last_health']
        context['last_health'] = health
        took_damage = (health is not None and previous_health is not None
                       and previous_health-health > .09)
        boxes = _power_boxes(frame, player) if mode == 'showdown' else []
        if enemies:
            target = min(enemies, key=lambda row: (row[0]-player[0])**2 + (row[1]-player[1])**2)
            dx, dy = target[0]-player[0], target[1]-player[1]
            distance = max(1., math.hypot(dx, dy))
            # Walk into range; strafe around enemies already in range.
            nearby = [enemy for enemy in enemies if
                      math.hypot(enemy[0]-player[0], enemy[1]-player[1]) < width*.25]
            if took_damage and distance < width*.28:
                context['dodge_until'] = time.monotonic() + .9
            if time.monotonic() < context['dodge_until'] and distance < width*.30:
                # Dodge diagonally away from the nearest attacker after a hit.
                side = 1 if player[0] < width/2 else -1
                move_dx, move_dy = -dx - side*dy, -dy + side*dx
                tactic = 'dodge'
            elif health is not None and health < .48 and distance > width*.30:
                move_dx, move_dy = -dx, -dy
                tactic = 'heal'
            elif len(nearby) >= 2:
                center_x = sum(enemy[0] for enemy in nearby)/len(nearby)
                center_y = sum(enemy[1] for enemy in nearby)/len(nearby)
                move_dx, move_dy = player[0]-center_x, player[1]-center_y
                tactic = 'escape_group'
            elif distance < width * tactics['range']:
                direction = -1 if int(time.monotonic() / 3) % 2 else 1
                if strategy == 'cautious' and distance < width * .16:
                    move_dx, move_dy = -dx, -dy
                else:
                    move_dx, move_dy = -dy * direction, dx * direction
            else:
                move_dx, move_dy = dx, dy
            attack_range = (.255 if brawler == 'shelly' else .29) * width
            if tactic == 'heal' or distance > attack_range:
                action = {'kind': 'none'}
            else:
                attack_x, attack_y = .897*width, .734*height
                if distance <= width*.20 and _super_ready(frame) and \
                        time.monotonic()-context.get('last_super', 0) > 3:
                    action = {'kind': 'super', 'x1': round(width*1512/1920),
                              'y1': round(height*881/1080)}
                    context['last_super'] = time.monotonic()
                elif distance <= width * tactics['auto_fire_range']:
                    action = {'kind': 'auto_fire', 'x1': round(attack_x),
                              'y1': round(attack_y), 'confidence': round(target[2], 3)}
                else:
                    attack_radius = .065*width
                    action = {'kind': 'attack', 'x1': round(attack_x), 'y1': round(attack_y),
                              'x2': clamp_x(attack_x + attack_radius*dx/distance),
                              'y2': clamp_y(attack_y + attack_radius*dy/distance),
                              'duration_ms': tactics['attack_ms'], 'confidence': round(target[2], 3)}
                if tactic not in ('dodge', 'escape_group'):
                    tactic = 'fight'
        elif boxes and (health is None or health >= .75):
            target = min(boxes, key=lambda box: (box[0]-player[0])**2 + (box[1]-player[1])**2)
            dx, dy = target[0]-player[0], target[1]-player[1]
            distance = max(1., math.hypot(dx, dy))
            close_range = .055 if brawler == 'shelly' else .095
            if distance > width*close_range:
                move_dx, move_dy = dx, dy
                action = {'kind': 'none'}
                tactic = 'approach_box'
            else:
                move_dx, move_dy = 0, 0
                attack_x, attack_y = .897*width, .734*height
                action = {'kind': 'auto_fire', 'x1': round(attack_x), 'y1': round(attack_y)}
                tactic = 'break_box'
        else:
            # The camera follows the player, so walking toward the frame center
            # keeps issuing the same direction indefinitely. Change bearings.
            if time.monotonic()-context['patrol_since'] > 1.6:
                context['patrol_since'] = time.monotonic()
                context['patrol_step'] = (context['patrol_step']+1) % 6
            bearings = ((1, -.3), (.4, -1), (-.8, -.4), (-1, .3), (-.3, 1), (.8, .6))
            move_dx, move_dy = bearings[context['patrol_step']]
            action = {'kind': 'none'}
        move_len = math.hypot(move_dx, move_dy)
        if move_len > .01:
            move_x, move_y = .094*width, .833*height
            move_radius = .065*width
            movement = {'kind': 'move', 'x1': round(move_x), 'y1': round(move_y),
                        'x2': clamp_x(move_x + move_radius*move_dx/move_len),
                        'y2': clamp_y(move_y + move_radius*move_dy/move_len),
                        'duration_ms': 420, 'confidence': round(player[2], 3)}
            context['last_move'] = movement
    else:
        action = {'kind': 'none'}
        if time.monotonic()-context['last_player_seen'] < 1.5:
            movement = context['last_move']
    return {'action': action, 'state': state, 'state_confidence': state_confidence,
            'width': width, 'height': height, 'movement': movement, 'strategy': strategy,
            'mode': mode or 'unknown', 'health': round(health, 2) if health is not None else None,
            'tactic': tactic, 'super_ready': _super_ready(frame) if player else False,
            'detections': {name: len(rows) for name, rows in found.items()},
            'timings_ms': {'decode': round((decoded-started)*1000, 1),
                           'inference': round((inferred-decoded)*1000, 1),
                           'total': round((time.perf_counter()-started)*1000, 1)}}
