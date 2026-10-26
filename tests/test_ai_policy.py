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
        assert hit['action']['kind'] in ('attack', 'auto_fire')
        ai_engine._contexts['test_damage']['dodge_until'] = 0
        with patch.object(ai_engine, 'ready', return_value=Session(550)):
            heal = ai_engine.decide(frame_png(28), device_id='test_damage')
        assert heal['tactic'] == 'heal'
        assert heal['action']['kind'] == 'none'


def test_close_enemy_holds_fire_and_super():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    with patch.object(pyla_state, 'classify', return_value=('match', 0)), \
            patch.object(ai_engine, 'ready', return_value=Session(350)):
        png = cv2.imencode('.png', frame)[1].tobytes()
        attack = ai_engine.decide(png, device_id='test_close')
        assert attack['action']['kind'] == 'auto_fire'
        cv2.rectangle(frame, (487, 277), (515, 305), (0, 210, 255), -1)
        charged = ai_engine.decide(cv2.imencode('.png', frame)[1].tobytes(), device_id='test_close')
        assert charged['action']['kind'] == 'super'
    controller = ldphone_agent.TouchController.__new__(ldphone_agent.TouchController)
    controller.fire_held = False
    with patch.object(controller, 'send') as send:
        controller.auto_fire(500, 250, 640, 360)
        controller.auto_fire(500, 250, 640, 360)
        assert send.call_count == 1
        controller.release_fire()
        assert send.call_count == 2


def test_patrol_changes_direction_and_remembers_target_briefly():
    blank = frame_png()
    with patch.object(pyla_state, 'classify', return_value=('match', 0)):
        with patch.object(ai_engine, 'ready', return_value=Session(400)):
            first = ai_engine.decide(blank, device_id='test_patrol')
            assert first['action']['kind'] == 'attack'
        with patch.object(ai_engine, 'ready', return_value=Session()):
            remembered = ai_engine.decide(blank, device_id='test_patrol')
            assert remembered['action']['kind'] == 'attack'
            ai_engine._contexts['test_patrol']['last_enemy_seen'] = 0
            first_patrol = ai_engine.decide(blank, device_id='test_patrol')
            assert first_patrol['tactic'] == 'patrol'
            ai_engine._contexts['test_patrol']['patrol_since'] = 0
            next_patrol = ai_engine.decide(blank, device_id='test_patrol')
            assert next_patrol['movement']['x2'] != first_patrol['movement']['x2']


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
