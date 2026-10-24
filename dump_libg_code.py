# Python 3 / rooted Android Termux / dump executable libg.so mappings
"""Copy loaded executable code pages without injecting into the game."""

from pathlib import Path
import subprocess
import zipfile

PACKAGE = 'com.supercell.brawlstars'
OUTPUT = Path('/sdcard/Download/libg_code.zip')
CHUNK = 1024 * 1024


def main():
    result = subprocess.run(['/system/bin/pidof', PACKAGE], capture_output=True, text=True)
    if result.returncode or not result.stdout.strip():
        raise SystemExit('Abre o Brawl Stars e deixa-o no menu antes de executar o comando.')
    pid = result.stdout.split()[0]
    mappings = []
    for line in Path(f'/proc/{pid}/maps').read_text().splitlines():
        parts = line.split()
        if len(parts) < 6 or not parts[-1].endswith('/libg.so') or 'x' not in parts[1]:
            continue
        start, end = (int(x, 16) for x in parts[0].split('-'))
        mappings.append((start, end, int(parts[2], 16), line))
    if not mappings:
        raise SystemExit('Não encontrei páginas executáveis de libg.so; confirma que o jogo está aberto.')
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(f'/proc/{pid}/mem', 'rb', buffering=0) as memory:
        with zipfile.ZipFile(OUTPUT, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.writestr('maps.txt', '\n'.join(row[3] for row in mappings) + '\n')
            for start, end, offset, _ in mappings:
                position = 0
                while position < end - start:
                    size = min(CHUNK, end - start - position)
                    memory.seek(start + position)
                    data = memory.read(size)
                    if len(data) != size:
                        raise RuntimeError(f'Leitura incompleta em {start + position:x}')
                    archive.writestr(f'code_{offset + position:08x}.bin', data)
                    position += size
                print(f'Copiado código em offset {offset:08x}: {(end-start)/1048576:.1f} MiB', flush=True)
    print(f'Criado: {OUTPUT} ({OUTPUT.stat().st_size} bytes)', flush=True)


if __name__ == '__main__':
    main()

