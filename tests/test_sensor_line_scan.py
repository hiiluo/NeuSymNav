"""Large fragmented RGB replies must not repeatedly scan their entire prefix."""
import sys,time
from neusymnav.perception.detector_client import _BoundedProcess


def test_fragmented_sensor_reply_has_linear_delimiter_search_work(tmp_path,monkeypatch):
    import neusymnav.perception.detector_client as transport
    script=tmp_path/'worker.py'
    script.write_text("import sys,json\nsys.stdin.readline()\nsys.stdout.write(json.dumps({'pixels':'x'*524288})+'\\n')\nsys.stdout.flush()\n")
    real_read=transport.os.read
    monkeypatch.setattr(transport.os,'read',lambda fd,size:real_read(fd,min(size,2048)))
    class CountedBuffer(bytearray):
        scanned=0
        def find(self,needle,start=0,end=None):
            self.scanned+=max(0,(len(self) if end is None else end)-start)
            return super().find(needle,start) if end is None else super().find(needle,start,end)
    wire=_BoundedProcess([sys.executable,str(script)],timeout_s=5.,response_limit=1024**2,lines=True)
    wire.buffer=CountedBuffer()
    try:
        wire.start();deadline=time.monotonic()+5.
        wire.send({'capture':True},deadline)
        result=wire.receive(deadline)
        assert result=={'pixels':'x'*524288}
        assert wire.buffer.scanned<=2*524320, 'delimiter search rescans the growing RGB prefix'
    finally:
        wire.close(2.)


def test_next_receive_scans_retained_complete_reply_from_start(tmp_path):
    script=tmp_path/'two.py'
    script.write_text("import sys\nsys.stdin.readline()\nsys.stdout.write('{\"a\":1}\\n{\"b\":2}\\n')\nsys.stdout.flush()\n")
    wire=_BoundedProcess([sys.executable,str(script)],timeout_s=5.,response_limit=1024,lines=True)
    try:
        wire.start();deadline=time.monotonic()+5.
        wire.send({},deadline)
        assert wire.receive(deadline)=={'a':1}
        assert wire.receive(deadline)=={'b':2}
    finally:wire.close(2.)
