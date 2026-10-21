# Python 3.12 / Linux / Supercell ID email and PIN authentication
import base64
import json

import requests

API = "https://ingame.id.supercell.com/api/account"


class ScidError(RuntimeError):
    pass


def _post(session, method, fields):
    try:
        response = session.post(f"{API}/{method}", data=fields, timeout=20)
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ScidError(f"Falha na ligação ao Supercell ID: {exc}") from exc
    if not body.get("ok"):
        raise ScidError(f"Supercell ID recusou {method}: {body.get('error', 'resposta sem detalhes')}")
    return body.get("data") or {}


def start(session, email):
    _post(session, "login", {"email": email, "game": "laser", "env": "prod", "lang": "pt"})


def confirm(session, email, pin):
    _post(session, "login.validate", {"email": email, "pin": pin})
    data = _post(session, "login.confirm", {"email": email, "pin": pin})
    token = data.get("bindToken")
    jwt = data.get("scid")
    if not token or not jwt:
        raise ScidError("O Supercell ID não devolveu bindToken/scid. Este fluxo antigo não permite iniciar sessão na versão atual.")
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        pid = json.loads(base64.urlsafe_b64decode(payload))["pid"]
        hi, lo = (int(part) for part in pid.split("-", 1))
        if not (0 <= hi < 2**32 and 0 <= lo < 2**32):
            raise ValueError("pid fora do intervalo")
    except (IndexError, KeyError, ValueError, TypeError) as exc:
        raise ScidError("O Supercell ID devolveu um ID de conta inválido") from exc
    return hi, lo, token
