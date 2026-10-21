# Python 3.12 / ShardCloud / web interface for the Brawl Stars TCP client
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from flask import Flask, jsonify, render_template_string, request
from waitress import serve

from client import Version, run

app = Flask(__name__)
jobs = {}
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
<h1>Entrar na sala</h1><p>Introduz os dados da tua conta e o código da sala.</p>
<form id="join" autocomplete="off">
<label for="code">Código da sala</label><input id="code" name="code" maxlength="64" required autocapitalize="characters">
<div class="row"><div><label for="hi">ID alto</label><input id="hi" name="hi" type="number" value="0" required></div>
<div><label for="lo">ID baixo</label><input id="lo" name="lo" type="number" value="0" required></div></div>
<label for="token">Token da conta</label><input id="token" name="token" type="password" autocomplete="off" required>
<button id="submit" type="submit">Entrar na sala</button>
</form><div id="result" role="status" aria-live="polite"></div>
<p class="hint">O token é usado apenas nesta tentativa. A página não o guarda.</p>
</main><script>
const form=document.getElementById('join'),result=document.getElementById('result'),button=document.getElementById('submit');
function show(value){result.style.display='block';result.textContent=value}
form.addEventListener('submit',async ev=>{
  ev.preventDefault();button.disabled=true;show('A iniciar ligação...');
  try{
    const body=new FormData(form);const r=await fetch('/join',{method:'POST',body,cache:'no-store'});
    const data=await r.json();if(!r.ok)throw Error(data.error||'Erro ao iniciar');
    document.getElementById('token').value='';
    for(;;){
      await new Promise(resolve=>setTimeout(resolve,1200));
      const status=await fetch('/status/'+encodeURIComponent(data.id),{cache:'no-store'});
      const job=await status.json();if(!status.ok)throw Error(job.error||'Erro ao consultar');
      show(job.lines.join('\n') || 'A ligar ao servidor...');
      if(job.done)break;
    }
  }catch(error){show(error.message)}finally{button.disabled=false}
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


@app.post("/join")
def join():
    code = request.form.get("code", "").strip().lstrip("#").upper()
    token = request.form.get("token", "")
    try:
        hi = int(request.form.get("hi", ""))
        lo = int(request.form.get("lo", ""))
    except ValueError:
        return jsonify(error="ID alto ou baixo inválido"), 400
    if not code or len(code) > 64 or any(not (c.isascii() and c.isalnum()) for c in code):
        return jsonify(error="Código da sala inválido"), 400
    if not token or len(token) > 4096:
        return jsonify(error="Token inválido"), 400
    if not (0 <= hi < 2**32 and 0 <= lo < 2**32):
        return jsonify(error="ID fora do intervalo"), 400
    job_id = secrets.token_urlsafe(24)
    with lock:
        now = time.monotonic()
        for old_id in list(jobs):
            if jobs[old_id]["done"] and now - jobs[old_id]["created"] > 900:
                del jobs[old_id]
        if sum(not job["done"] for job in jobs.values()) >= 2:
            return jsonify(error="Já existem duas tentativas em curso. Aguarda um momento."), 429
        jobs[job_id] = {"lines": [], "done": False, "created": now}
    args = SimpleNamespace(code=code, hi=hi, lo=lo, token=token,
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
