# Python 3.12 / ShardCloud / application entry point
import os
import logging
import sys
import threading
from urllib.request import urlopen

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('brawl-room.startup')


try:
    from waitress import serve
    from server import app
except Exception:
    log.exception('startup_import_failed')
    raise


if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', '80'))
        log.info('startup_bind host=0.0.0.0 port=%s', port)
        def selfcheck():
            try:
                with urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as response:
                    log.info('startup_selfcheck status=%s', response.status)
            except Exception:
                log.exception('startup_selfcheck_failed')
        threading.Timer(2, selfcheck).start()
        serve(app, host='0.0.0.0', port=port, threads=4)
    except Exception:
        log.exception('startup_serve_failed')
        raise
