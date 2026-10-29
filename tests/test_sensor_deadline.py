"""Sensor publication must include decode and validation in the IPC deadline."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.sensors.client import HabitatPoseSource
from neusymnav.sensors.habitat_worker import encode_packet, normalize_capture


def source_fixture(tmp_path, size=2):
    packet=encode_packet(normalize_capture(rgb=None,depth=np.ones((size,size),np.float32),
        K=np.eye(3),T_world_habitat=np.eye(4),episode_id='deadline',sensor_id='nav',frame_index=0,
        capture_monotonic_ns=time.monotonic_ns(),clock_domain='host_monotonic:test',sim_time_s=0.,
        calibration_id='cpu-fixture',pose_version=0,modality='depth_only',depth_min_m=.1,depth_max_m=10.))
    # Pixels and wire bytes are prepared before ready; the child does real pipe
    # IO with no decode monkeypatch or delayed response.
    worker=tmp_path/'sensor.py'
    worker.write_text('import sys,json\n'
        f'response={json.dumps(dict(ok=True,packet=packet))!r}\n'
        'print(json.dumps(dict(ready=True,wire_version=1)),flush=True)\n'
        'for line in sys.stdin: print(response,flush=True)\n')
    return HabitatPoseSource(python=sys.executable,config={},timeout_s=3.,worker_script=worker)


@pytest.mark.parametrize('stage', ['npz', 'calibration', 'source'])
def test_decode_and_validation_share_transport_deadline(tmp_path,monkeypatch,stage):
    import neusymnav.sensors.client as module
    source=source_fixture(tmp_path)
    source.timeout_s=.05
    clock=[time.monotonic()]
    receive=source._wire.receive
    def timed_receive(deadline):
        result=receive(deadline)
        clock[0] += .04
        return result
    source._wire.receive=timed_receive
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    if stage=='source':
        class SlowWatermarks(dict):
            def get(self,*args):
                result=super().get(*args)
                clock[0] += .02
                return result
        source._last=SlowWatermarks()
    else:
        target,name=(module.np,'frombuffer') if stage=='npz' else (module,'Observation')
        original=getattr(target,name)
        def slow_decode(*args,**kwargs):
            result=original(*args,**kwargs)
            clock[0] += .02
            return result
        monkeypatch.setattr(target,name,slow_decode)
    try:
        with pytest.raises(TimeoutError,match='deadline'):
            source.capture_navigation()
        assert not source.is_alive and source._navigation is None
        assert source._last_capture_ns == -1
        with pytest.raises(RuntimeError,match='closed'):
            source.capture_navigation()
    finally:
        assert source.close()['clean_shutdown']


def test_real_cpu_subprocess_never_publishes_after_operation_timeout(tmp_path):
    # A bounded 512x512 packet exercises actual JSON/base64/NPZ/Observation work.
    # Different budgets avoid depending on one scheduler threshold. Any success
    # must arrive within its original budget; timeout must poison the client.
    for timeout in (.008,.010,.012,.015,.020):
        source=source_fixture(tmp_path,size=512)
        source.timeout_s=timeout
        started=time.monotonic()
        try:
            try:
                result=source.capture_navigation()
            except TimeoutError:
                assert not source.is_alive and source._navigation is None
            else:
                assert time.monotonic()-started <= timeout
                assert result.depth_m.shape==(512,512)
        finally:
            assert source.close()['clean_shutdown']
