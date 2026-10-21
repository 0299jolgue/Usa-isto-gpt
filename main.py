# Python 3.12 / ShardCloud / application entry point
import os

from waitress import serve

from server import app


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', '80')), threads=4)
