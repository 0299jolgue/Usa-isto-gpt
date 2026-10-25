# Python 3.12 / ShardCloud / Brawl Stars room bridge website
import logging
from flask import Flask, jsonify, redirect, request, send_file
from room_bridge import _agent, bridge

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.register_blueprint(bridge)
log = logging.getLogger('brawl-room')


@app.get('/')
def index():
    return redirect('/bridge', code=302)


@app.get('/health')
def health():
    return 'ok', 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.get('/agent.py')
def agent_script():
    return send_file('ldphone_agent.py', mimetype='text/x-python; charset=utf-8')


@app.post('/ai/ready')
def ai_ready():
    if not _agent():
        return jsonify(error='unauthorized'), 401
    try:
        from ai_engine import ready
        ready()
        return jsonify(ok=True)
    except Exception as exc:
        log.exception('ai_ready_failed')
        return jsonify(error=f'{type(exc).__name__}: {exc}'), 503


@app.post('/ai/step')
def ai_step():
    if not _agent():
        return jsonify(error='unauthorized'), 401
    if request.mimetype != 'image/png':
        return jsonify(error='expected image/png'), 415
    try:
        from ai_engine import decide
        return jsonify(decide(request.get_data(cache=False)))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        log.exception('ai_step_failed')
        return jsonify(error=f'{type(exc).__name__}: {exc}'), 503
