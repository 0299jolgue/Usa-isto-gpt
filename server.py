# Python 3.12 / ShardCloud / web interface for the Brawl Stars TCP client
import os
import secrets
import threading
import time
import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from flask import Flask, jsonify, render_template_string, request
from waitress import serve
import requests

from client import Version, run
from scid import ScidError, start as scid_start, confirm as scid_confirm

app = Flask(__name__)
jobs = {}
pending = {}
lock = threading.Lock()
workers = ThreadPoolExecutor(max_workers=2)

PAGE = """<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Entrar na sala · Brawl Stars</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#f2f5ff;background:#0c1224}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px}
main{width:min(100%,470px);background:#18213a;border:1px solid #314168;border-radius:20px;padding:28px;box-shadow:0 20px 50px #05091366}
h1{margin:0 0 8px;font-size:1.7rem}p{color:#b8c4df;margin:0 0 22px;line-height:1.5}
label{display:block;font-weight:650;margin:16px 0 7px}input{width:100%;padding:13px 14px;border:1px solid #506189;border-radius:10px;background:#10182b;color:white;font:inherit}
input:focus{outline:2px solid #65a9ff;border-color:#65a9ff}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button{width:100%;border:0;border-radius:10px;background:#ffc928;color:#16203c;font-weight:800;font:inherit;padding:14px;margin-top:22px;cursor:pointer}
button:disabled{opacity:.65;cursor:wait}#result{white-space:pre-wrap;word-break:break-word;background:#10182b;border-radius:10px;padding:14px;margin-top:18px;display:none;line-height:1.5}
.hint{font-size:.85rem;margin-top:18px;margin-bottom:0}
</style></head><body><main>
<h1>Entrar na sala</h1><p>Introduz o email da conta Supercell ID e o código da sala. Depois, confirma o PIN recebido por email.</p>
<form id="join" autocomplete="off">
<label for="code">Código da sala</label><input id="code" name="code" maxlength="64" required autocapitalize="characters">
<label for="email">Email do Supercell ID</label><input id="email" name="email" type="email" required autocomplete="email">
<button id="submit" type="submit">Enviar PIN</button>
</form><form id="pinForm" style="display:none" autocomplete="off"><label for="pin">PIN recebido por email</label><input id="pin" name="pin" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required autocomplete="one-time-code"><button id="confirm" type="submit">Confirmar e entrar</button></form>
<div id="result" role="status" aria-live="polite"></div>
<p class="hint">A sessão fica apenas em memória durante esta tentativa.</p>
</main><script>
const form=document.getElementById('join'),result=document.getElementById('result'),button=document.getElementById('submit');
function show(value){result.style.display='block';result.textContent=value}
let challenge=null;
form.addEventListener('submit',async ev=>{
  ev.preventDefault();button.disabled=true;show('A pedir o PIN...');
  try{
    const body=new FormData(form);const r=await fetch('/auth/start',{method:'POST',body,cache:'no-store'});
    const data=await r.json();if(!r.ok)throw Error(data.error||'Erro ao iniciar');
    challenge=data.id;form.style.display='none';document.getElementById('pinForm').style.display='block';show('PIN enviado. Introduz o código recebido por email.');
  }catch(error){show(error.message)}finally{button.disabled=false}
});
document.getElementById('pinForm').addEventListener('submit',async ev=>{
  ev.preventDefault();const confirm=document.getElementById('confirm');confirm.disabled=true;show('A confirmar o PIN...');
  try{
    const body=new FormData(ev.target);body.set('id',challenge);const r=await fetch('/auth/confirm',{method:'POST',body,cache:'no-store'});
    const data=await r.json();if(!r.ok)throw Error(data.error||'Erro ao confirmar');
    document.getElementById('pin').value='';
    for(;;){
      await new Promise(resolve=>setTimeout(resolve,1200));
      const status=await fetch('/status/'+encodeURIComponent(data.id),{cache:'no-store'});
      const job=await status.json();if(!status.ok)throw Error(job.error||'Erro ao consultar');
      show(job.lines.join('\\n') || 'A ligar ao servidor...');
      if(job.done)break;
    }
  }catch(error){show(error.message)}finally{confirm.disabled=false}
});
</script></body></html>"""


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def index():
    return render_template_string(PAGE)


def execute(job_id, args):
    def emit(*parts):
        with lock:
            jobs[job_id]["lines"].append(" ".join(map(str, parts)))

    try:
        version = Version()
        for _ in range(2):
            if run(args, version, emit=emit):
                emit("Pedido concluído.")
                break
        else:
            raise RuntimeError("Não foi possível atualizar a versão")
    except Exception as exc:
        emit(f"Erro: {type(exc).__name__}: {exc}")
    finally:
        with lock:
            jobs[job_id]["done"] = True
        args.token = None


@app.post("/auth/start")
def auth_start():
    code = request.form.get("code", "").strip().lstrip("#").upper()
    email = request.form.get("email", "").strip().lower()
    if not code or len(code) > 64 or any(not (c.isascii() and c.isalnum()) for c in code):
        return jsonify(error="Código da sala inválido"), 400
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return jsonify(error="Email inválido"), 400
    session = requests.Session()
    try:
        scid_start(session, email)
    except ScidError as exc:
        session.close()
        return jsonify(error=str(exc)), 502
    challenge = secrets.token_urlsafe(24)
    with lock:
        now = time.monotonic()
        for old_id in list(pending):
            if now - pending[old_id]["created"] > 600:
                pending.pop(old_id)["session"].close()
        pending[challenge] = {"email": email, "code": code, "session": session, "created": now}
    return jsonify(id=challenge), 202


@app.post("/auth/confirm")
def auth_confirm():
    challenge = request.form.get("id", "")
    pin = request.form.get("pin", "")
    if not re.fullmatch(r"[0-9]{6}", pin):
        return jsonify(error="PIN inválido"), 400
    with lock:
        auth = pending.pop(challenge, None)
    if auth is None or time.monotonic() - auth["created"] > 600:
        return jsonify(error="Sessão expirada. Pede um novo PIN."), 400
    try:
        hi, lo, token = scid_confirm(auth["session"], auth["email"], pin)
    except ScidError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        auth["session"].close()
    job_id = secrets.token_urlsafe(24)
    with lock:
        now = time.monotonic()
        for old_id in list(jobs):
            if jobs[old_id]["done"] and now - jobs[old_id]["created"] > 900:
                del jobs[old_id]
        if sum(not job["done"] for job in jobs.values()) >= 2:
            return jsonify(error="Já existem duas tentativas em curso. Aguarda um momento."), 429
        jobs[job_id] = {"lines": [], "done": False, "created": now}
    args = SimpleNamespace(code=auth["code"], hi=hi, lo=lo, token=token,
                           host="game.brawlstarsgame.com", port=9339)
    workers.submit(execute, job_id, args)
    return jsonify(id=job_id), 202


@app.get("/status/<job_id>")
def status(job_id):
    with lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify(error="Tentativa não encontrada"), 404
        return jsonify(lines=list(job["lines"]), done=job["done"])


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), threads=4)
