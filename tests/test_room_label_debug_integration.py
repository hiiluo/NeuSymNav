import os,json,hashlib
from pathlib import Path
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def test_dashboard_optional_snapshot_tab_is_separate_and_disabled_by_default():
    from PyQt5 import QtWidgets
    from neusymnav.visualization.desktop import DashboardWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Service:
        current_graph=None
        def records(self):return ()
        def status(self):return {'pending':0,'world_epoch':None}
        def offer(self,g):return True
    base=DashboardWindow(clock_domain='host:test');assert not hasattr(base,'room_label_debug') or base.room_label_debug is None;base.close()
    window=DashboardWindow(clock_domain='host:test',room_label_service=Service())
    assert window.room_label_debug is not None
    assert any('Room labels' in window.scene_tabs.tabText(i) for i in range(window.scene_tabs.count()))
    window.close();app.processEvents()


def test_debug_factory_bad_hash_is_local_unavailable_service(tmp_path):
    from neusymnav.rooms.debug_runtime import create_debug_service
    p=tmp_path/'model.json';p.write_text('{}')
    svc=create_debug_service({'config_path':str(p),'config_sha256':'a'*64,'taxonomy_path':str(p),'taxonomy_sha256':'a'*64},artifact_root=tmp_path/'out')
    assert svc.records()==() and svc.status()['error']
    assert svc.close(1)['clean_shutdown']


def test_optin_runtime_ui_schema_accepts_only_explicit_pinned_debug_assets(tmp_path):
    from neusymnav.runtime.configuration import load_config
    p=Path('configs/demo-00807.hydra-world2hz-room-stability.experimental.local.json');c=json.loads(p.read_text())
    config=Path('configs/room-label-slm.experimental.json').absolute();taxonomy=Path('configs/taxonomy-v1.json').absolute()
    c['ui']['room_label_debug']={'config_path':str(config),'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'taxonomy_path':str(taxonomy),'taxonomy_sha256':hashlib.sha256(taxonomy.read_bytes()).hexdigest()}
    entry=Path('src/neusymnav/runtime/room_label_ui_entry.py').resolve()
    c['workers']['ui']['script']={'path':str(entry),'sha256':hashlib.sha256(entry.read_bytes()).hexdigest()}
    out=tmp_path/'profile.json';out.write_text(json.dumps(c));assert load_config(out).data['ui']['room_label_debug']
    c['ui']['room_label_debug']['config_sha256']='a'*64;out.write_text(json.dumps(c))
    with pytest.raises(ValueError,match='hash'):load_config(out)


def test_optin_ui_child_starts_and_closes_without_model_work_when_no_graph(tmp_path,monkeypatch):
    import sys,time
    from neusymnav.runtime.room_label_ui_entry import RoomLabelUiProcess
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    cfg=Path('configs/room-label-slm.async-debug.local.json').resolve();tax=Path('configs/taxonomy-v1.json').resolve()
    opts={'config_path':str(cfg),'config_sha256':hashlib.sha256(cfg.read_bytes()).hexdigest(),'taxonomy_path':str(tax),'taxonomy_sha256':hashlib.sha256(tax.read_bytes()).hexdigest()}
    ui=RoomLabelUiProcess(tmp_path/'ipc',room_label_debug=opts,python=sys.executable,
        script=Path('src/neusymnav/runtime/room_label_ui_entry.py').resolve(),clock_domain='clock',command_handler=lambda c:None,smoke_exit_ms=2500)
    try:
        end=time.monotonic()+5
        while not (ui.root/'ready.json').exists() and time.monotonic()<end:time.sleep(.02)
        assert (ui.root/'ready.json').exists()
        end=time.monotonic()+5
        while not (ui.root/'room-label-debug'/'rendered.json').exists() and time.monotonic()<end:time.sleep(.02)
        assert (ui.root/'room-label-debug'/'rendered.json').exists()
    finally:report=ui.close(5)
    assert report['clean_shutdown'],report
    assert report['room_label_debug']['clean_shutdown']
    assert not report['room_label_debug']['worker_pending']


def test_unavailable_debug_ui_renders_status_and_closes_without_artifact_directory(tmp_path,monkeypatch):
    import sys,time
    from neusymnav.runtime.room_label_ui_entry import RoomLabelUiProcess
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    cfg=Path('configs/room-label-slm.experimental.json').resolve();tax=Path('configs/taxonomy-v1.json').resolve()
    opts={'config_path':str(cfg),'config_sha256':hashlib.sha256(cfg.read_bytes()).hexdigest(),'taxonomy_path':str(tax),'taxonomy_sha256':hashlib.sha256(tax.read_bytes()).hexdigest()}
    ui=RoomLabelUiProcess(tmp_path/'ipc',room_label_debug=opts,python=sys.executable,
        script=Path('src/neusymnav/runtime/room_label_ui_entry.py').resolve(),clock_domain='clock',command_handler=lambda c:None,smoke_exit_ms=2500)
    try:
        p=ui.root/'room-label-debug'/'rendered.json';end=time.monotonic()+5
        while not p.exists() and time.monotonic()<end:time.sleep(.02)
        assert p.exists()
        assert 'disabled' in json.loads(p.read_text())['service']['error']
    finally:report=ui.close(5)
    assert report['clean_shutdown']


def test_shared_zoom_controls_operate_on_selected_debug_snapshot():
    from PyQt5 import QtWidgets
    from neusymnav.visualization.desktop import DashboardWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Service:
        current_graph=None
        def records(self):return ()
        def status(self):return {}
        def offer(self,g):return False
    window=DashboardWindow(clock_domain='clock',room_label_service=Service())
    try:
        window.scene_tabs.setCurrentWidget(window.room_label_debug)
        view=window.room_label_debug.snapshot_graph;before=view.transform().m11()
        window._zoom_graph(1.25)
        assert view.transform().m11()>before
    finally:window.close();app.processEvents()


def test_historical_debug_tab_hides_unrelated_live_image_sidebar():
    from PyQt5 import QtWidgets
    from neusymnav.visualization.desktop import DashboardWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Service:
        current_graph=None
        def records(self):return ()
        def status(self):return {}
        def offer(self,g):return False
    window=DashboardWindow(clock_domain='clock',room_label_service=Service())
    try:
        window.scene_tabs.setCurrentWidget(window.room_label_debug)
        assert window.graph_split.widget(1).isHidden()
        assert window.cloud_menu_button.isHidden()
        window.scene_tabs.setCurrentWidget(window.spatial_view)
        assert not window.graph_split.widget(1).isHidden()
        assert not window.cloud_menu_button.isHidden()
    finally:window.close();app.processEvents()
