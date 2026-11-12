"""Opt-in debug UI entry; legacy ui_transport source and pins stay unchanged."""
from pathlib import Path
import sys,json,time
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from neusymnav.runtime.ui_transport import UiProcess,_write_atomic
from neusymnav.rooms.debug_runtime import validate_debug_options


class RoomLabelUiProcess(UiProcess):
    def __init__(self,root,*,room_label_debug,script,**kwargs):
        if Path(script).resolve()!=Path(__file__).resolve():raise ValueError('room debug requires pinned room_label_ui_entry.py')
        validate_debug_options(room_label_debug)
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        _write_atomic(root/'room-label-launch.json',json.dumps(room_label_debug).encode())
        quota=kwargs.get('quota')
        if quota is not None:quota.reserve('room-label-debug',12*1024*1024)
        super().__init__(root,script=script,**kwargs)

    def close(self,timeout_s=1.):
        report=super().close(timeout_s)
        try:
            p=self.root/'room-label-debug'/'shutdown.json'
            if p.stat().st_size>4096:raise ValueError('debug shutdown report exceeds cap')
            child=json.loads(p.read_text())
        except Exception as exc:child={'clean_shutdown':False,'error':str(exc)[:256]}
        return {**report,'clean_shutdown':bool(report['clean_shutdown']) and child.get('clean_shutdown') is True,'room_label_debug':child}


def main():
    # Legacy main retains command/ACK, publication and shutdown ownership.
    from PyQt5 import QtCore,QtWidgets
    from neusymnav.visualization import desktop
    from neusymnav.runtime import ui_transport
    from neusymnav.rooms.debug_runtime import create_debug_service
    from neusymnav.rooms.debug_types import record_is_current
    root=Path(sys.argv[sys.argv.index('--root')+1]);debugroot=root/'room-label-debug'
    debugroot.mkdir(parents=True,exist_ok=True)
    options=json.loads((root/'room-label-launch.json').read_text())
    service=create_debug_service(options,artifact_root=debugroot)
    original=desktop.run_desktop
    def shutdown():
        report=service.close(3.)
        debugroot.mkdir(parents=True,exist_ok=True)
        _write_atomic(debugroot/'shutdown.json',json.dumps(report).encode())
        return report
    def run(*args,**kwargs):
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        app.aboutToQuit.connect(shutdown)
        timer=QtCore.QTimer(app);timer.setInterval(500);captured=[False]
        def observe():
            for window in app.topLevelWidgets():
                widget=getattr(window,'room_label_debug',None)
                if widget is None:continue
                record=widget.selected_record
                data={'schema_version':1,'experimental':True,'service':service.status(),'selected':None}
                if record is not None:
                    data['selected']={'request_id':record.job.request.request_id,'source_revision':record.job.request.key.graph_revision,'source_run_id':record.job.request.key.run_id,'context_hash':record.job.request.key.context_hash,'state':record.state,'label':None if record.result is None else record.result.label,'status':None if record.result is None else record.result.status,'is_current':record_is_current(record,service.current_graph),'source_snapshot_sha256':record.job.request.key.geometry_hash}
                    if not captured[0] and record.result is not None:
                        path=debugroot/'snapshot-ui.png';window.grab().save(str(path))
                        if path.exists() and path.stat().st_size>2*1024*1024:path.unlink()
                        captured[0]=True
                _write_atomic(debugroot/'rendered.json',json.dumps(data).encode())
                return
        timer.timeout.connect(observe);timer.start()
        kwargs['room_label_service']=service
        try:return original(*args,**kwargs)
        finally:
            timer.stop()
            try:observe()
            finally:shutdown()
    desktop.run_desktop=run
    try:return ui_transport.main()
    finally:desktop.run_desktop=original;shutdown()


if __name__=='__main__':raise SystemExit(main())
