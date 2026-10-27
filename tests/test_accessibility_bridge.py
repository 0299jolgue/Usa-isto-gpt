# Python 3.12 / local test / Android accessibility broadcast fallback
from types import SimpleNamespace
from unittest.mock import patch

import ldphone_agent as agent


def test_token_read_from_android_preferences():
    xml = '<map><string name="token">abcDEF_123456789012345678901</string></map>'
    with patch.object(agent.subprocess, 'run',
                      return_value=SimpleNamespace(returncode=0, stdout=xml)):
        assert agent.accessibility_token() == 'abcDEF_123456789012345678901'


def test_movement_and_attack_use_one_gesture():
    movement = {'x1': 50, 'y1': 250, 'x2': 90, 'y2': 240}
    action = {'kind': 'auto_fire', 'x1': 550, 'y1': 250}
    response = SimpleNamespace(returncode=0, stdout='Broadcast completed: result=1', stderr='')
    with patch.object(agent.subprocess, 'run', return_value=response) as run, \
            patch.object(agent.time, 'sleep'):
        agent.accessibility_gesture('abcDEF_123456789012345678901',
                                    movement, action, 640, 360)
        shell = run.call_args.args[0][2]
        assert '--es kind auto_fire' in shell
        assert '--ei moving 1' in shell
        assert '--ei mx2 90' in shell
        assert '--ei ax1 550' in shell


def test_disabled_service_has_clear_error():
    response = SimpleNamespace(returncode=0, stdout='Broadcast completed: result=2', stderr='')
    with patch.object(agent.subprocess, 'run', return_value=response):
        try:
            agent.accessibility_gesture('abcDEF_123456789012345678901', None,
                                        {'kind': 'tap', 'x1': 500, 'y1': 250}, 640, 360)
        except RuntimeError as exc:
            assert 'Ativa Brawl Room Menu' in str(exc)
        else:
            raise AssertionError('Expected disabled-service error')
