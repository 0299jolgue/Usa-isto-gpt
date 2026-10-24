# Python 3 / Termux aarch64 / rooted Android / Frida 17 CLI
"""Capture a redacted official LoginMessage before encryption."""

from pathlib import Path
import select
import subprocess
import time

PACKAGE = 'com.supercell.brawlstars'
FRIDA = '/data/data/com.termux/files/usr/bin/frida-inject'
AGENT = Path('/sdcard/Download/brawl_login_agent.js')
OUTPUT = Path('/sdcard/Download/brawl_login_redacted.bin')
TIMEOUT = 90

JS = r"""
const OFFSET = 0xf2b03c;
let installed = false;
function install(module) {
  if (installed || module.name !== 'libg.so') return;
  installed = true;
  console.log('HOOK_INSTALLED:' + module.base);
  Interceptor.attach(module.base.add(OFFSET), {
    onEnter(args) { this.object = args[0]; },
    onLeave() {
      try {
        const stream = this.object.add(8);
        const size = stream.add(0x14).readU32();
        const pointer = stream.add(0x38).readPointer();
        if (size < 64 || size > 16384 || pointer.isNull()) {
          console.log('CAPTURE_ERROR:invalid size ' + size);
          return;
        }
        const data = new Uint8Array(pointer.readByteArray(size));
        const tokenSize = (data[8] * 0x1000000 + (data[9] << 16) + (data[10] << 8) + data[11]) | 0;
        if (tokenSize < -1 || tokenSize > 4096 || 12 + Math.max(tokenSize, 0) > size) {
          console.log('CAPTURE_ERROR:unexpected token length ' + tokenSize);
          return;
        }
        data.fill(0, 0, 8);
        if (tokenSize > 0) data.fill(0, 12, 12 + tokenSize);
        let hex = '';
        for (const value of data) hex += value.toString(16).padStart(2, '0');
        console.log('CAPTURE_HEX:' + hex);
      } catch (error) {
        console.log('CAPTURE_ERROR:' + String(error));
      }
    }
  });
}
Process.attachModuleObserver({onAdded(module) { install(module); }});
"""


def main():
    if not Path(FRIDA).exists():
        raise SystemExit('frida-inject não encontrado. Executa: pkg install frida')
    AGENT.write_text(JS)
    pid_result = subprocess.run(['su', '-c', f'/system/bin/pidof {PACKAGE}'],
                                capture_output=True, text=True)
    pids = pid_result.stdout.split()
    if not pids:
        raise SystemExit('Abre o Brawl Stars, espera chegar ao menu e volta ao Termux sem fechar o jogo.')
    pid = pids[0]
    command = ['su', '-c', f'{FRIDA} -p {pid} -s {AGENT}']
    print(f'A ligar ao Brawl Stars já aberto (PID {pid})...', flush=True)
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    deadline = time.monotonic() + TIMEOUT
    reconnected = False
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([proc.stdout], [], [], 1)
            if not readable:
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline().strip()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            marker = 'CAPTURE_HEX:'
            if marker in line:
                payload = bytes.fromhex(line.split(marker, 1)[1].strip())
                OUTPUT.write_bytes(payload)
                print(f'Captura criada: {OUTPUT} ({len(payload)} bytes)', flush=True)
                return
            print(line, flush=True)
            if 'HOOK_INSTALLED:' in line and not reconnected:
                reconnected = True
                print('A provocar uma reconexão TCP...', flush=True)
                insert = subprocess.run(
                    ['su', '-c', '/system/bin/iptables -I OUTPUT -p tcp --dport 9339 -j REJECT'],
                    capture_output=True, text=True,
                )
                if insert.returncode:
                    print('Não consegui interromper a ligação:', insert.stderr.strip(), flush=True)
                    print('Alterna o modo avião no Android e volta ao jogo.', flush=True)
                else:
                    try:
                        time.sleep(12)
                    finally:
                        subprocess.run(
                            ['su', '-c', '/system/bin/iptables -D OUTPUT -p tcp --dport 9339 -j REJECT'],
                            capture_output=True, text=True,
                        )
                    print('Ligação TCP reposta; aguarda o jogo reconectar.', flush=True)
        running = subprocess.run(
            ['su', '-c', f'/system/bin/pidof {PACKAGE}'], capture_output=True, text=True,
        )
        print('PID do jogo:', running.stdout.strip() or 'não encontrado', flush=True)
        logs = subprocess.run(
            ['su', '-c', '/system/bin/logcat -d -t 500'], capture_output=True, text=True,
        )
        relevant = [line for line in logs.stdout.splitlines()
                    if 'frida' in line.lower() or PACKAGE in line.lower()
                    or 'fatal exception' in line.lower()]
        for line in relevant[-15:]:
            print('LOG:', line[-300:], flush=True)
        raise SystemExit(f'Não capturei o login. frida-inject saiu com código {proc.poll()}.')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main()
