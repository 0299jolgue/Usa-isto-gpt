# Python 3.12 / local pytest / synthetic frames for combat policy decisions
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

import ai_engine
import ldphone_agent
import pyla_state


class Session:
    def __init__(self, enemy=None):
        self.enemy = enemy

    def get_inputs(self):
        return [SimpleNamespace(name='image')]

    def run(self, *_):
        raw = np.zeros((7, 2 if self.enemy else 1), dtype=np.float32)
        raw[:4, 0] = [320, 180, 44, 50]
        raw[6, 0] = .95
        if self.enemy:
            raw[:4, 1] = [self.enemy, 180, 40, 45]
            raw[4, 1] = .9
        return [raw[None]]


def frame_png(health_width=70, crate=False):
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (280, 140), (280 + health_width, 145), (0, 230, 0), -1)
    if crate:
        cv2.rectangle(frame, (415, 160), (460, 207), (0, 145, 220), -1)
        cv2.rectangle(frame, (418, 150), (455, 154), (0, 230, 0), -1)
    return cv2.imencode('.png', frame)[1].tobytes()


def test_damage_triggers_dodge_then_heal():
    with patch.object(pyla_state, 'classify', return_value=('match', 0)), \
            patch.object(ai_engine, 'ready', return_value=Session(450)):
        ai_engine.decide(frame_png(), device_id='test_damage')
        hit = ai_engine.decide(frame_png(28), device_id='test_damage')
        assert hit['tactic'] == 'dodge'
        assert hit['action']['kind'] == 'none'
        ai_engine._contexts['test_damage']['dodge_until'] = 0
        heal = ai_engine.decide(frame_png(28), device_id='test_damage')
        assert heal['tactic'] == 'heal'
        assert heal['action']['kind'] == 'none'


def test_crate_only_in_showdown():
    with patch.object(pyla_state, 'classify', return_value=('match', 0)), \
            patch.object(ai_engine, 'ready', return_value=Session()):
        box = ai_engine.decide(frame_png(crate=True), mode='showdown', brawler='shelly')
        assert box['tactic'] == 'approach_box'
        assert ai_engine.decide(frame_png(crate=True))['tactic'] == 'patrol'


def test_mode_ocr():
    with patch.object(ldphone_agent.shutil, 'which', return_value='tesseract'), \
            patch.object(ldphone_agent.subprocess, 'run',
                         return_value=SimpleNamespace(returncode=0, stdout=b'COMBATE SOLO SHELLY')):
        assert ldphone_agent.read_lobby_loadout(b'png') == {
            'mode': 'showdown', 'brawler': 'shelly'}
