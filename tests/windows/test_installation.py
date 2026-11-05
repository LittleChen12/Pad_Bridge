# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from padbridge_app.windows import installation


def test_helper_path_cleanup_does_not_traverse_unrelated_junctions(monkeypatch, tmp_path):
    bundle = tmp_path / 'bundle'
    other = tmp_path / 'untrusted-other-app-junction'
    keep = tmp_path / 'system-tools'
    monkeypatch.setattr(installation.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(installation.sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setenv('PATH', os.pathsep.join(map(str, (bundle, other, bundle / 'nested', keep))))
    monkeypatch.setattr(Path, 'resolve', Mock(side_effect=OSError(448, 'untrusted junction')))
    reset = Mock(return_value=True)
    monkeypatch.setattr(installation.ctypes, 'WinDLL', lambda *a, **kw: SimpleNamespace(SetDllDirectoryW=reset))
    installation.prepare_system_helper()
    reset.assert_called_once_with(None)
    assert os.environ['PATH'].split(os.pathsep) == [str(other), str(keep)]
