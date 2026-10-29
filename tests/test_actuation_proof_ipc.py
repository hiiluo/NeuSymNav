from dataclasses import asdict,replace
import copy
import sys
from pathlib import Path
import pytest
from test_sensor_actuation import actuator,execute
from contract_helpers import observation
from neusymnav.contracts import FrameKey
from neusymnav.runtime.actuation_measurements import validate_actuation_proof


def paired(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    obs=observation(key=c.source,capture_monotonic_ns=c.source_capture_monotonic_ns,clock_domain=c.clock_domain,pose_version=4,modality='depth_only')
    w._navigation_state['calibration_id']=obs.calibration_id
    return w,c,calls,clock,obs


def test_native_step_proof_has_actual_body_pose_source_and_digest(monkeypatch):
    w,c,calls,clock,obs=paired(monkeypatch)
    result=execute(w,c)
    proof=w.last_actuation_proof
    checked=validate_actuation_proof(proof,c,obs)
    assert checked['body_translation_m']==pytest.approx(result['displacement_m'])
    assert proof['actions'][0]['body_before_xy']==[2.,-4.]
    assert proof['actions'][0]['body_after_xy']==pytest.approx([2.,-3.98])
    assert proof['actions'][0]['pre_step_monotonic_ns']==clock[0]
    execute(w,c)
    assert w.last_actuation_proof is None


def test_slow_proof_preparation_cannot_extend_ttl(monkeypatch):
    w,c,calls,clock,obs=paired(monkeypatch)
    import neusymnav.sensors.habitat_worker as worker
    original=worker.canonical_robot_pose
    def slow(state):
        result=original(state);clock[0]+=110_000_000;return result
    monkeypatch.setattr(worker,'canonical_robot_pose',slow)
    result=execute(w,c)
    assert not result['executed'] and not calls


def test_actual_two_steps_have_pose_and_time_chain(monkeypatch):
    w,c,calls,clock,obs=paired(monkeypatch);c=replace(c,yaw_radps=.2)
    execute(w,c);checked=validate_actuation_proof(w.last_actuation_proof,c,obs)
    assert checked['action_count']==2
    assert checked['proof']['actions'][1]['pose_version_before']==5


def test_native_exception_clears_old_proof(monkeypatch):
    w,c,calls,clock,obs=paired(monkeypatch)
    w.last_actuation_proof={'old':True}
    w.agent.act=lambda _:(_ for _ in ()).throw(RuntimeError('broken native'))
    with pytest.raises(RuntimeError):execute(w,c)
    assert w.last_actuation_proof is None


def proof_worker(tmp_path,*,corrupt=False):
    # Copy the existing read-only CPU fixture; only its response gains a proof.
    base=Path(__file__).parent/'fixtures/actuation/worker.py'
    text=base.read_text().replace("result = dict(actuation=worker.execute(request['command'],request['pose_version']))", "result = dict(actuation=worker.execute(request['command'],request['pose_version']),actuation_proof=worker.last_actuation_proof)")
    if corrupt:text=text.replace("print(json.dumps(dict(ok=True,**result)),flush=True)","\n    if op=='execute' and result['actuation_proof'] is not None:result['actuation_proof']['command_sha256']='0'*64\n    print(json.dumps(dict(ok=True,**result)),flush=True)")
    # Preserve local package import despite moving fixture into tmp_path.
    text=text.replace("sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))",f"sys.path.insert(0,{str(Path(__file__).resolve().parents[1]/'src')!r})")
    path=tmp_path/'proof-worker.py';path.write_text(text);return path


def command_for(obs):
    import time
    from neusymnav.contracts import MotionCommand
    now=time.monotonic_ns()
    return MotionCommand(obs.key,1,now,now+100_000_000,obs.clock_domain,.2,0.,'frontier',obs.capture_monotonic_ns)


def test_real_ipc_body_proof_and_detached_snapshot(tmp_path):
    from neusymnav.sensors.client import HabitatPoseSource
    p=HabitatPoseSource(python=sys.executable,config={},worker_script=proof_worker(tmp_path),timeout_s=2)
    try:
        obs=p.capture_navigation();c=command_for(obs)
        result=p.execute(c);proof=p.last_actuation_proof
        assert validate_actuation_proof(proof,c,obs)['body_translation_m']==pytest.approx(result['displacement_m'])
        proof['actions'].clear();assert len(p.last_actuation_proof['actions'])==1
        p.execute(c);assert p.last_actuation_proof is None
    finally:assert p.close()['clean_shutdown']


def test_real_ipc_bad_proof_rejected_and_child_reaped(tmp_path):
    from neusymnav.sensors.client import HabitatPoseSource
    p=HabitatPoseSource(python=sys.executable,config={},worker_script=proof_worker(tmp_path,corrupt=True),timeout_s=2)
    obs=p.capture_navigation()
    with pytest.raises(ValueError):p.execute(command_for(obs))
    assert p.last_actuation_proof is None and not p.is_alive


def test_execute_proof_validation_cannot_escape_operation_deadline(tmp_path,monkeypatch):
    import time
    from neusymnav.sensors.client import HabitatPoseSource
    import neusymnav.runtime.actuation_measurements as module
    p=HabitatPoseSource(python=sys.executable,config={},worker_script=proof_worker(tmp_path),timeout_s=2)
    original=module.validate_actuation_proof
    try:
        obs=p.capture_navigation();p.timeout_s=.05
        def slow(*a,**kw):
            result=original(*a,**kw);time.sleep(.08);return result
        monkeypatch.setattr(module,'validate_actuation_proof',slow)
        with pytest.raises(TimeoutError):p.execute(command_for(obs))
        assert p.last_actuation_proof is None and not p.is_alive
    finally:p.close()


def test_later_step_cannot_be_followed_by_old_execute_proof_publication(tmp_path, monkeypatch):
    import threading
    import neusymnav.runtime.actuation_measurements as measurements
    from neusymnav.sensors.client import HabitatPoseSource
    worker = proof_worker(tmp_path)
    text = worker.read_text().replace(
        "    else:\n        raise ValueError('invalid fixture operation')",
        "    elif op == 'step':\n        worker.step(request['action'])\n        result = {}\n    else:\n        raise ValueError('invalid fixture operation')")
    worker.write_text(text)
    p = HabitatPoseSource(python=sys.executable, config={}, worker_script=worker, timeout_s=2.)
    entered, release = threading.Event(), threading.Event()
    original = measurements.validate_actuation_proof
    failures = []
    def paused(*args, **kwargs):
        checked = original(*args, **kwargs)
        entered.set()
        assert release.wait(1.)
        return checked
    monkeypatch.setattr(measurements, 'validate_actuation_proof', paused)
    obs = p.capture_navigation()
    def run():
        try:
            p.execute(command_for(obs))
        except Exception as exc:
            failures.append(exc)
    thread = threading.Thread(target=run)
    try:
        thread.start()
        assert entered.wait(1.)
        # The first native pulse has returned, but host validation is paused.
        p.step('__neusymnav_guarded_pulse__')
        assert p.last_actuation_proof is None
        release.set()
        thread.join(1.)
        assert not thread.is_alive()
        assert p.last_actuation_proof is None
    finally:
        release.set()
        thread.join(1.)
        p.close()

