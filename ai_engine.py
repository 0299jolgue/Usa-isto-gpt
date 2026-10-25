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


def decide(png):
    import cv2
    import numpy as np
    started = time.perf_counter()
    frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('Captura PNG inválida')
    height, width = frame.shape[:2]
    if not (500 <= width <= 4096 and 300 <= height <= 2160):
        raise ValueError('Dimensões da captura inválidas')
    decoded = time.perf_counter()
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
    enemies = found['enemy']
    if player and enemies:
        target = min(enemies, key=lambda row: (row[0]-player[0])**2 + (row[1]-player[1])**2)
        dx, dy = target[0]-player[0], target[1]-player[1]
        import math
        distance = max(1., math.hypot(dx, dy))
        base_x, base_y = .897*width, .734*height  # Pyla's 1920x1080 attack stick
        radius = .065*width
        action = {'kind': 'attack', 'x1': round(base_x), 'y1': round(base_y),
                  'x2': round(base_x + radius*dx/distance),
                  'y2': round(base_y + radius*dy/distance), 'duration_ms': 120,
                  'confidence': round(target[2], 3)}
    elif player:
        # Briefly move toward the arena center until an enemy is visible.
        dx, dy = width/2-player[0], height/2-player[1]
        import math
        distance = max(1., math.hypot(dx, dy))
        base_x, base_y = .094*width, .833*height
        radius = .065*width
        action = {'kind': 'move', 'x1': round(base_x), 'y1': round(base_y),
                  'x2': round(base_x + radius*dx/distance),
                  'y2': round(base_y + radius*dy/distance), 'duration_ms': 160,
                  'confidence': round(player[2], 3)}
    else:
        action = {'kind': 'none'}
    return {'action': action, 'width': width, 'height': height,
            'detections': {name: len(rows) for name, rows in found.items()},
            'timings_ms': {'decode': round((decoded-started)*1000, 1),
                           'inference': round((inferred-decoded)*1000, 1),
                           'total': round((time.perf_counter()-started)*1000, 1)}}
