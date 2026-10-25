# Python 3.12 / ShardCloud / Brawl Stars room bridge website
import logging
from flask import Flask, redirect, send_file
from room_bridge import bridge

app = Flask(__name__)
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
