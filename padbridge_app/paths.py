import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'padbridge'
MARKER = RUNTIME / 'connector.json'
CONNECTION = RUNTIME / 'connection.json'
CONFIG = ROOT / 'settings.toml'
UNIT = 'padbridge.service'
LAUNCHER = str(ROOT / 'padbridge')
