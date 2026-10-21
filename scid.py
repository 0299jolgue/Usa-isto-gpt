# Python 3.12 / Linux / Supercell ID email and PIN authentication
import base64
import json
import logging
import uuid

import requests

APIS = (
    "https://id.supercell.com/api/ingame/account",
    "https://ingame.id.supercell.com/api/account",
)
log = logging.getLogger('brawl-room.scid')


class ScidError(RuntimeError):
    pass


def _post(session, method, fields):
    try:
        bases = (getattr(session, "scid_api"),) if hasattr(session, "scid_api") else APIS
        for base in bases:
            log.info('scid_request method=%s base=%s', method, base)
            response = session.post(f"{base}/{method}", data=fields, timeout=(5, 10))
            log.info('scid_response method=%s status=%s', method, response.status_code)
            if response.status_code == 404 and not hasattr(session, "scid_api"):
                continue
            session.scid_api = base
            break
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ScidError(f"Falha na ligação ao Supercell ID: {exc}") from exc
    if not body.get("ok"):
        raise ScidError(f"Supercell ID recusou {method}: {body.get('error', 'resposta sem detalhes')}")
    return body.get("data") or {}


def start(session, email):
    session.headers.update({
        "User-Agent": "scid/4527-i (iOS 17.4.1; laser-prod; iPhone13,1)",
        "X-Supercell-Device-Id": str(uuid.uuid4()).upper(),
    })
    _post(session, "login", {"email": email, "game": "laser", "env": "prod", "lang": "pt", "remember": "true"})


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
