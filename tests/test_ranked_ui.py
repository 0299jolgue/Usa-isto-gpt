# Python 3.12 / local tests / Ranked selection from game OCR
from types import SimpleNamespace
from unittest.mock import patch

import ldphone_agent as agent


def word(text, x=600, y=500, confidence=90):
    return {'text': text, 'x': x, 'y': y, 'confidence': confidence}


def test_ranked_selection_requires_confirmation():
    lobby = [word('JOGAR', 1100, 600), word('COMBATE', 720, 590)]
    chooser = [word('RANQUEADO', 630, 290)]
    selected = [word('RANQUEADO', 700, 590), word('JOGAR', 1100, 600)]
    launch = SimpleNamespace(returncode=0)
    with patch.object(agent.subprocess, 'run', return_value=launch), \
            patch.object(agent, 'accessibility_token', return_value=None), \
            patch.object(agent, '_screen_png', return_value=(b'png', 1280, 720)), \
            patch.object(agent, '_ocr_words', side_effect=[lobby, chooser, selected]), \
            patch.object(agent, '_tap_game') as tap, patch.object(agent.time, 'sleep'):
        status, detail = agent.select_ranked()
        assert status == 'available' and 'Jogar' in detail
        assert tap.call_count == 2
        assert tap.call_args_list[0].args[:2] == (720, 590)
        assert tap.call_args_list[1].args[:2] == (630, 290)


def test_locked_ranked_does_not_start_game():
    lobby = [word('JOGAR', 1100, 600), word('COMBATE', 720, 590)]
    chooser = [word('RANQUEADO', 630, 290), word('BLOQUEADO', 640, 350)]
    with patch.object(agent.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
            patch.object(agent, 'accessibility_token', return_value=None), \
            patch.object(agent, '_screen_png', return_value=(b'png', 1280, 720)), \
            patch.object(agent, '_ocr_words', side_effect=[lobby, chooser]), \
            patch.object(agent, '_tap_game') as tap, patch.object(agent.time, 'sleep'):
        status, _ = agent.select_ranked()
        assert status == 'locked'
        assert tap.call_count == 1


def test_unknown_screen_does_not_tap():
    with patch.object(agent.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
            patch.object(agent, 'accessibility_token', return_value=None), \
            patch.object(agent, '_screen_png', return_value=(b'png', 1280, 720)), \
            patch.object(agent, '_ocr_words', return_value=[]), \
            patch.object(agent, '_tap_game') as tap, patch.object(agent.time, 'sleep'):
        status, _ = agent.select_ranked()
        assert status == 'unknown'
        tap.assert_not_called()
