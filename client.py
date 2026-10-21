# Python 3.11+ / Linux / Brawl Stars official TCP protocol (experimental v69)
import argparse
import hashlib
import json
import os
import socket
import struct
from dataclasses import dataclass

from nacl.bindings import (
    crypto_box_afternm,
    crypto_box_beforenm,
    crypto_box_open_afternm,
    crypto_scalarmult_base,
)

SERVER_KEY = bytes.fromhex("5f4bfa1dc7b58fac0611f34dbaf3847b376f968530f76a9a202849017aa9510a")


def i32(value):
    return struct.pack(">I", value & 0xFFFFFFFF)


def s(value):
    if value is None:
        return i32(-1)
    encoded = value.encode()
    return i32(len(encoded)) + encoded


def vint(value):
    first = ((value >> 25) & 0x40) | (value & 0x3F)
    remaining = (value ^ (value >> 31)) >> 6
    value >>= 6
    if remaining == 0:
        return bytes([first])
    out = bytearray([first | 0x80])
    while True:
        remaining >>= 7
        out.append((value & 0x7F) | (0x80 if remaining else 0))
        value >>= 7
        if not remaining:
            return bytes(out)


def increment(nonce):
    return ((int.from_bytes(nonce[:4], "little") + 2) & 0xFFFFFFFF).to_bytes(4, "little") + nonce[4:]


def derive_nonce(*items):
    digest = hashlib.blake2b(digest_size=24)
    for item in items:
        digest.update(item)
    return digest.digest()


@dataclass
class Version:
    major: int = 59
    minor: int = 219
    build: int = 1
    sha: str = "08dae21938f2f66e9a1dcc3d857b5fdf7f0e3eb8"


def hello(v):
    return b"".join([i32(2), i32(48), i32(v.major), i32(v.build), i32(v.minor), s(v.sha), i32(2), i32(2)])


def login(v, hi, lo, token):
    return b"".join([
        i32(hi), i32(lo), s(token), i32(v.major), i32(v.build), i32(v.minor), s(v.sha),
        s(None), vint(1), vint(0), s("en-US"), s(None), b"\0", s(None), s(None),
        b"\1", s(None), i32(1448), vint(0), s(None), s(None), s(None), vint(0),
        s(None), s(None), s(None), s(None), b"\0", s(None), s(None),
    ])


def read_exact(sock, count):
    result = bytearray()
    while len(result) < count:
        chunk = sock.recv(count - len(result))
        if not chunk:
            raise ConnectionError("Servidor fechou a ligação")
        result.extend(chunk)
    return bytes(result)


def read_packet(sock):
    header = read_exact(sock, 7)
    typ = int.from_bytes(header[:2], "big")
    size = int.from_bytes(header[2:5], "big")
    if size > 4_000_000:
        raise ValueError(f"Pacote demasiado grande: {size}")
    return typ, read_exact(sock, size)


def send_packet(sock, typ, body):
    sock.sendall(typ.to_bytes(2, "big") + len(body).to_bytes(3, "big") + b"\0\0" + body)


def read_string(data, offset):
    if offset + 4 > len(data):
        raise ValueError("String truncada")
    length = int.from_bytes(data[offset:offset + 4], "big", signed=True)
    if length < 0:
        return None
    if length > len(data) - offset - 4:
        raise ValueError("String truncada")
    return data[offset + 4:offset + 4 + length].decode(errors="replace")


def handle_login_failure(data, version, emit):
    if len(data) < 4:
        raise RuntimeError(f"LoginFailed truncado: {data.hex()}")
    code = int.from_bytes(data[:4], "big", signed=True)
    emit("Login recusado. Código:", code)
    try:
        description = read_string(data, 4)
        obj = json.loads(description or "")
    except (ValueError, TypeError):
        obj = None
    if code == 7 and isinstance(obj, dict) and "sha" in obj and "version" in obj:
        try:
            parts = [int(x) for x in obj["version"].split(".")]
        except (AttributeError, ValueError):
            parts = []
        if len(parts) == 3:
            version.major, version.minor, version.build = parts
            version.sha = obj["sha"]
            emit("Versão atualizada:", obj["version"])
            return False
    raise RuntimeError(f"Login recusado pelo servidor (código {code}; dados {data[:80].hex()})")


def run(args, v, emit=print):
    secret = os.urandom(32)
    public = crypto_scalarmult_base(secret)
    shared = crypto_box_beforenm(SERVER_KEY, secret)
    client_nonce = os.urandom(24)
    first_nonce = derive_nonce(public, SERVER_KEY)
    with socket.create_connection((args.host, args.port), timeout=15) as sock:
        sock.settimeout(30)
        send_packet(sock, 10100, hello(v))
        typ, response = read_packet(sock)
        emit("Recebido:", typ, len(response), "bytes")
        if typ == 20103:
            return handle_login_failure(response, v, emit)
        if typ != 20100 or len(response) < 28:
            raise RuntimeError("ServerHello inesperado")
        session_key = response[4:28]
        payload = session_key + client_nonce + login(v, args.hi, args.lo, args.token)
        send_packet(sock, 10101, public + crypto_box_afternm(payload, first_nonce, shared))
        while True:
            typ, response = read_packet(sock)
            if typ in (20103, 20104):
                nonce = derive_nonce(client_nonce, public, SERVER_KEY)
                plain = crypto_box_open_afternm(response, nonce, shared)
                server_nonce, shared = plain[:24], plain[24:56]
                data = plain[56:]
            else:
                server_nonce = increment(server_nonce)
                data = crypto_box_open_afternm(response, server_nonce, shared)
            emit("Recebido:", typ, len(data), "bytes")
            if typ == 20103:
                return handle_login_failure(data, v, emit)
            if typ == 20104:
                emit("Login aceite")
                # Constructor x1 receives the room code; encode writes that
                # string, then a boolean, integer, and optional trailing data.
                join = s(args.code) + b"\0" + i32(-1) + vint(0)
                client_nonce = increment(client_nonce)
                send_packet(sock, 14371, crypto_box_afternm(join, client_nonce, shared))
                emit("Pedido de entrada enviado. A aguardar resposta...")
            if typ == 20108:
                client_nonce = increment(client_nonce)
                send_packet(sock, 10108, crypto_box_afternm(b"", client_nonce, shared))
            if typ == 24129:
                raise RuntimeError(f"Servidor recusou a entrada na equipa: {data[:120].hex()}")
            if typ in (24124, 24131):
                emit("Estado da equipa:", typ, data[:120].hex())
                return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("code", help="Código da sala")
    parser.add_argument("--hi", type=int, default=int(os.environ.get("BS_HI", "0")))
    parser.add_argument("--lo", type=int, default=int(os.environ.get("BS_LO", "0")))
    parser.add_argument("--token", default=os.environ.get("BS_TOKEN", ""))
    parser.add_argument("--guest", action="store_true", help="Criar uma conta convidada com ID 0:0 e token nulo")
    parser.add_argument("--host", default="game.brawlstarsgame.com")
    parser.add_argument("--port", type=int, default=9339)
    args = parser.parse_args()
    if args.guest:
        args.hi = args.lo = 0
        args.token = None
    v = Version()
    for _ in range(2):
        if run(args, v):
            return
    raise RuntimeError("Não foi possível atualizar a versão")


if __name__ == "__main__":
    main()
