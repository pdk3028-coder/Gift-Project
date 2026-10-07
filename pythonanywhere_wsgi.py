"""WSGI entry point for PythonAnywhere; persistent data stays outside the checkout."""
import ipaddress
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_ROOT = Path(os.environ.get('GIFT_DATA_DIR', Path.home() / 'gift-data')).resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('GIFT_DATABASE', str(DATA_ROOT / 'employees.db'))
os.environ.setdefault('GIFT_INSTANCE', str(DATA_ROOT / 'instance'))
os.environ.setdefault('GIFT_UPLOAD_FOLDER', str(DATA_ROOT / 'uploads'))
os.environ['GIFT_HTTPS'] = '1'
os.environ['GIFT_TRUSTED_PROXY_HOPS'] = '0'

from app import app  # noqa: E402


def application(environ, start_response):
    # PythonAnywhere overwrites X-Real-IP at its load balancer. Its forwarded
    # list is not trustworthy: https://help.pythonanywhere.com/pages/WebAppClientIPAddresses/
    real_ip = environ.get('HTTP_X_REAL_IP', '')
    try:
        environ['REMOTE_ADDR'] = str(ipaddress.ip_address(real_ip))
    except ValueError:
        pass
    return app(environ, start_response)
