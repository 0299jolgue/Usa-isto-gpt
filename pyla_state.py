# Python 3.12 / ShardCloud / PylaAI screen-state templates pinned to commit 284714d
"""Recognize lobby, matchmaking and match-end screens at any landscape resolution."""
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen
import os

COMMIT = '284714d262b4c8a583e1fb0f34ef021b153d29e2'
BASE = f'https://raw.githubusercontent.com/PylaAI/PylaAI/{COMMIT}/images/'
CACHE = Path(os.environ.get('PYLA_STATE_DIR', '/tmp/pyla-states'))
# PylaAI's regions are specified for a 1920x1080 capture.
STATES = (
    ('end', 'end_results/victory.png', (20, 10, 650, 200), .78),
    ('end', 'end_results/defeat.png', (20, 10, 650, 200), .78),
    ('end', 'end_results/draw.png', (20, 10, 650, 200), .78),
    ('end', 'end_results/1st.png', (20, 10, 650, 200), .85),
    ('end', 'end_results/2nd.png', (20, 10, 650, 200), .85),
    ('end', 'end_results/3rd.png', (20, 10, 650, 200), .85),
    ('end', 'end_results/4th.png', (20, 10, 650, 200), .85),
    ('lobby', 'states/lobby_menu.png', (1790, 20, 75, 65), .78),
    ('match_making', 'states/exit_match_making.png', (0, 925, 340, 135), .78),
    ('trophy_reward', 'states/trophies_screen.png', (1545, 915, 365, 168), .78),
)


@lru_cache(maxsize=32)
def _source_template(path):
    import cv2
    import numpy as np
    target = CACHE / path
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(BASE + path, timeout=20) as response:
            data = response.read(250_000)
        if len(data) < 100 or len(data) >= 250_000:
            raise RuntimeError(f'PylaAI template inválido: {path}')
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
    image = cv2.imdecode(np.frombuffer(target.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        target.unlink(missing_ok=True)
        raise RuntimeError(f'PylaAI template corrompido: {path}')
    return image


@lru_cache(maxsize=48)
def _scaled_template(path, width, height):
    import cv2
    source = _source_template(path)
    w = max(1, round(source.shape[1] * width / 1920))
    h = max(1, round(source.shape[0] * height / 1080))
    return cv2.resize(source, (w, h), interpolation=cv2.INTER_AREA)


def classify(frame):
    import cv2
    height, width = frame.shape[:2]
    for state, path, (x, y, w, h), threshold in STATES:
        x1, y1 = round(x * width / 1920), round(y * height / 1080)
        x2, y2 = round((x + w) * width / 1920), round((y + h) * height / 1080)
        region = frame[y1:y2, x1:x2]
        template = _scaled_template(path, width, height)
        if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
            continue
        score = float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max())
        if score >= threshold:
            return state, round(score, 3)
    return 'match', 0.0
