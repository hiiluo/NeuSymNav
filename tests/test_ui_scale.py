"""Scale the external demo UI, leaving host/control scaling untouched."""
import json
from pathlib import Path
import sys
import time
from neusymnav.runtime.ui_transport import UiProcess


def test_external_demo_preserves_desktop_scale_without_extra_zoom(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    monkeypatch.setenv('QT_SCALE_FACTOR','1.0')
    monkeypatch.setenv('QT_AUTO_SCREEN_SCALE_FACTOR','0')
    monkeypatch.delenv('QT_SCREEN_SCALE_FACTORS',raising=False)
    script=Path(__file__).parents[1]/'src/neusymnav/runtime/ui_transport.py'
    ui=UiProcess(tmp_path,python=sys.executable,script=script,clock_domain='clock',
        command_handler=lambda command:None,smoke_exit_ms=300)
    try:
        deadline=time.monotonic()+5
        while not (tmp_path/'ready.json').exists() and time.monotonic()<deadline:time.sleep(.01)
        ready=json.loads((tmp_path/'ready.json').read_text())
        assert ready['device_pixel_ratio']==1.0
        import os
        assert os.environ['QT_SCALE_FACTOR']=='1.0'
    finally:assert ui.close(2)['clean_shutdown']
