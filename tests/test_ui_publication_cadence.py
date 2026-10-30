"""The bounded UI worker coalesces handoffs before source preparation."""
from contextlib import contextmanager
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from neusymnav.contracts import FrameKey
from neusymnav.runtime import ui_transport
from neusymnav.visualization.publisher import UiCommand, UiCommandAck
from contract_helpers import observation
from test_display_snapshot import make_publisher


@contextmanager
def ui_process(tmp_path, **kwargs):
    script = tmp_path / 'idle.py'
    script.write_text('import time\ntime.sleep(30)\n')
    ui = ui_transport.UiProcess(tmp_path / 'ipc', python=sys.executable,
        script=script, clock_domain='clock',
        command_handler=lambda c: UiCommandAck(c.request_uuid, 'accepted', None,
                                               time.monotonic_ns(), 'clock'), **kwargs)
    try:
        yield ui
    finally:
        assert ui.close(2)['clean_shutdown']


def fixed_clock(monkeypatch):
    now = [1_000_000_000]
    monkeypatch.setattr(ui_transport, 'time', SimpleNamespace(
        monotonic_ns=lambda: now[0], monotonic=time.monotonic))
    return now


def wait_publication(ui, predicate=lambda value: True):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        path=ui.root/'publication.json'
        if path.exists():
            value=ui_transport.decode_publication(path.read_bytes())
            if predicate(value):return value
        time.sleep(.01)
    raise AssertionError('no expected asynchronous publication')


def test_handoffs_coalesce_without_source_preparation_on_graph_lane(tmp_path, monkeypatch):
    now = fixed_clock(monkeypatch)
    _, snapshot, metrics, *_ = make_publisher()
    with ui_process(tmp_path, publish_hz=2) as ui:
        ui.publish(snapshot, metrics)
        wait_publication(ui)
        calls=[]
        monkeypatch.setattr(ui, '_images', lambda sources:(calls.append(1), ())[1])
        for i in range(20):
            ui.publish(snapshot, dict(metrics,actual_profile=str(i)))
        time.sleep(.05)
        assert not calls
        assert ui.status['coalesced_publications']>=19
        now[0] += 500_000_000
        latest=wait_publication(ui,lambda e:e.metrics.actual_profile=='19')
        assert latest.metrics.actual_profile=='19' and calls==[1]
        assert ui.status['dropped_publications']==0


def test_next_worker_tick_uses_latest_rgb_and_graph_metadata(tmp_path, monkeypatch):
    now = fixed_clock(monkeypatch)
    _, snapshot, metrics, *_ = make_publisher()
    with ui_process(tmp_path, publish_hz=2) as ui:
        ui.publish(snapshot, metrics);wait_publication(ui)
        source = observation(key=FrameKey('e', 'rgbd', 77),
            capture_monotonic_ns=1_200_000_000, clock_domain='clock')
        now[0] = 1_300_000_000
        ui.set_rgb(source)
        ui.publish(snapshot, metrics)
        latest_metrics = dict(metrics, captured_frame_id=source.key,
            actual_profile='current-graph-call')
        ui.publish(snapshot, latest_metrics)
        now[0] = 1_500_000_000
        latest=wait_publication(ui,lambda e:e.metrics.actual_profile=='current-graph-call')
        assert latest.sources.rgb.source == FrameKey('e', 'rgbd', 77)
        assert latest.sources.rgb.capture_monotonic_ns == 1_200_000_000
        assert latest.metrics.source_age_ns['rgb'] == 300_000_000
        assert latest.metrics.captured_frame_id == source.key
        assert not latest.sources.rgb.pixels.flags.writeable
        assert ui.status['coalesced_publications']>=1
        assert ui.status['dropped_publications'] == 0


@pytest.mark.parametrize('publish_hz', [True, False, 0, -1, 20.1, float('nan'), float('inf'), '2', 10**400])
def test_invalid_cadence_rejected_before_startup(tmp_path, publish_hz):
    with pytest.raises(ValueError, match='publish_hz'):
        ui_transport.UiProcess(tmp_path / 'must-not-exist', python='missing', script='missing',
            clock_domain='clock', command_handler=lambda c: None, publish_hz=publish_hz)
    assert not (tmp_path / 'must-not-exist').exists()


@pytest.mark.parametrize('publish_hz', [None, 20, 2.5])
def test_default_and_configured_cadence_are_bounded_at_five_hz(tmp_path, monkeypatch, publish_hz):
    now = fixed_clock(monkeypatch)
    _, snapshot, metrics, *_ = make_publisher()
    with ui_process(tmp_path, publish_hz=publish_hz) as ui:
        assert ui._publish_hz==min(5.,publish_hz or 5.)
        ui.publish(snapshot, metrics);first=wait_publication(ui)
        ui.publish(snapshot, dict(metrics, actual_profile='second'))
        time.sleep(.05)
        assert ui.publisher.read_latest().publication_sequence==first.publication_sequence
        now[0]+=1_000_000_000
        assert wait_publication(ui,lambda e:e.metrics.actual_profile=='second')
        assert ui.status['dropped_publications'] == 0


@pytest.mark.parametrize('action', ['pause', 'stop'])
def test_coalescing_does_not_delay_command_ack(tmp_path, monkeypatch, action):
    fixed_clock(monkeypatch)
    _, snapshot, metrics, *_ = make_publisher()
    with ui_process(tmp_path, publish_hz=2) as ui:
        ui.publish(snapshot, metrics)
        ui.publish(snapshot, metrics)
        command = UiCommand(str(uuid4()), action, 'test', time.monotonic_ns(), 'clock')
        endpoint = ui_transport.UiEndpoint(ui.root, clock_domain='clock')
        endpoint.submit(command)
        deadline = time.monotonic() + 1
        acks = []
        while not acks and time.monotonic() < deadline:
            acks = endpoint.read_acks()
            if not acks:
                time.sleep(.01)
        assert acks and acks[0].request_uuid == command.request_uuid
        assert acks[0].status == 'accepted'
        assert ui.status['dropped_publications'] == 0
