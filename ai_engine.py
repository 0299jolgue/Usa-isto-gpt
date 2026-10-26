# Python 3.12 / ShardCloud Linux / PylaAI ONNX vision policy
"""Fast, single-frame enemy detection and a small Brawl Stars control policy."""

import hashlib
import logging
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


def decide(png, strategy='balanced'):
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
    # Only player (class 2) and enemy (class 0) centers are needed for the first policy.
    found = {}
    for class_id, label in ((2, 'player'), (0, 'enemy')):
        indices = np.flatnonzero((classes == class_id) & (confidence >= .55))
        indices = indices[np.argsort(confidence[indices])[-16:]]
        found[label] = [(float(raw[0, i] * width / resized_w), float(raw[1, i] * height / resized_h),
                         float(confidence[i])) for i in indices]
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
        'aggressive': {'range': .12, 'attack_ms': 180},
        'balanced': {'range': .18, 'attack_ms': 130},
        'cautious': {'range': .28, 'attack_ms': 100},
    }.get(strategy, {'range': .18, 'attack_ms': 130})
    movement = None
    if player:
        import math
        if enemies:
            target = min(enemies, key=lambda row: (row[0]-player[0])**2 + (row[1]-player[1])**2)
            dx, dy = target[0]-player[0], target[1]-player[1]
            distance = max(1., math.hypot(dx, dy))
            # Walk into range; strafe around enemies already in range.
            nearby = [enemy for enemy in enemies if
                      math.hypot(enemy[0]-player[0], enemy[1]-player[1]) < width*.25]
            if len(nearby) >= 2:
                center_x = sum(enemy[0] for enemy in nearby)/len(nearby)
                center_y = sum(enemy[1] for enemy in nearby)/len(nearby)
                move_dx, move_dy = player[0]-center_x, player[1]-center_y
            elif distance < width * tactics['range']:
                direction = -1 if int(time.monotonic() / 3) % 2 else 1
                if strategy == 'cautious' and distance < width * .16:
                    move_dx, move_dy = -dx, -dy
                else:
                    move_dx, move_dy = -dy * direction, dx * direction
            else:
                move_dx, move_dy = dx, dy
            attack_x, attack_y = .897*width, .734*height
            attack_radius = .065*width
            action = {'kind': 'attack', 'x1': round(attack_x), 'y1': round(attack_y),
                      'x2': clamp_x(attack_x + attack_radius*dx/distance),
                      'y2': clamp_y(attack_y + attack_radius*dy/distance),
                      'duration_ms': tactics['attack_ms'], 'confidence': round(target[2], 3)}
        else:
            # Patrol when the nearest enemy is outside the camera view.
            move_dx, move_dy = width/2-player[0], height/2-player[1]
            if math.hypot(move_dx, move_dy) < width * .07:
                direction = -1 if int(time.monotonic() / 4) % 2 else 1
                move_dx, move_dy = direction, .35
            action = {'kind': 'none'}
        move_len = max(1., math.hypot(move_dx, move_dy))
        move_x, move_y = .094*width, .833*height
        move_radius = .065*width
        movement = {'kind': 'move', 'x1': round(move_x), 'y1': round(move_y),
                    'x2': clamp_x(move_x + move_radius*move_dx/move_len),
                    'y2': clamp_y(move_y + move_radius*move_dy/move_len),
                    'duration_ms': 420, 'confidence': round(player[2], 3)}
    else:
        action = {'kind': 'none'}
    return {'action': action, 'state': state, 'state_confidence': state_confidence,
            'width': width, 'height': height, 'movement': movement, 'strategy': strategy,
            'detections': {name: len(rows) for name, rows in found.items()},
            'timings_ms': {'decode': round((decoded-started)*1000, 1),
                           'inference': round((inferred-decoded)*1000, 1),
                           'total': round((time.perf_counter()-started)*1000, 1)}}
