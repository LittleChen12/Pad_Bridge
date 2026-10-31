import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == 'win32'
if WINDOWS:
    USER_DATA = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'PadBridge'
    CONFIG_HOME = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'PadBridge'
    RUNTIME = USER_DATA / 'runtime'
else:
    CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'padbridge'
    USER_DATA = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'padbridge'
    RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'padbridge'
MARKER = RUNTIME / 'connector.json'
CONNECTION = RUNTIME / 'connection.json'
CONFIG = ROOT / 'settings.toml'
UNIT = 'padbridge.service'
LAUNCHER = str(ROOT / 'padbridge')
