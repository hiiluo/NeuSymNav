"""handoff/3dsg-v11: templatize -> install renders paths and re-pins every checked sha256."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'handoff/3dsg-v11' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_templates_round_trip_and_repin(tmp_path, monkeypatch):
    inst = _load('install')
    old = dict(repo='/home/u/NSN/wt', home='/home/u/NSN', data='/home/u/data', env='/home/u/conda/envs/habitat')
    src = tmp_path / 'src'
    # the frozen machine's files
    write(src / inst.HYDRA_LABELS, 'labels: 1\n')
    write(src / inst.HYDRA_DATASET, 'x: 1\nneusymnav_room_stability:\n  library_path: %s/runs/lib/libhydra.so\n'
          '  library_sha256: %s\n' % (old['repo'], 'a' * 64))
    write(src / inst.SLM, json.dumps(dict(model_path=old['repo'] + '/m.gguf', model_sha256='b' * 64,
                                          runtime_binary_path=old['repo'] + '/llama', runtime_sha256='c' * 64)))
    write(src / inst.TOUR, json.dumps(dict(scene=dict(path=old['data'] + '/s.glb', sha256='d' * 64), polyline_xy=[])))
    write(src / inst.PROFILE, json.dumps(dict(
        detector=dict(backend='openvino_gpu', device='intel:gpu', fallback_policy='torch_cpu',
                      checkpoint=dict(path=old['home'] + '/local-assets/y.pt', sha256='e' * 64),
                      openvino_model=dict(path=old['repo'] + '/ov.xml', sha256='f' * 64)),
        floor=dict(datum_source='measured:' + old['home'] + '/.runtime/cal.json'),
        workers=dict(sensor=dict(python=dict(path=old['env'] + '/bin/python', sha256='1' * 64))),
        scene_graph=dict(hydra=dict(config_root=old['repo'] + '/' + inst.HYDRA_ROOT, dataset_sha256='2' * 64,
                                    labelspace_sha256='3' * 64)),
        ui=dict(room_label_debug=dict(config_path=old['repo'] + '/' + inst.SLM, config_sha256='4' * 64,
                                      taxonomy_path=old['repo'] + '/tax.json', taxonomy_sha256='5' * 64)))))
    tz = _load('templatize')
    handoff = tmp_path / 'handoff'
    monkeypatch.setattr(tz, 'HERE', handoff)
    monkeypatch.setattr(tz, 'HYDRA_WS', [])
    paths = write(tmp_path / 'paths.json', json.dumps({'@REPO@': old['repo'], '@NSN_HOME@': old['home'],
                                                       '@HABITAT_DATA@': old['data'], '@HABITAT_ENV@': old['env']}))
    tz.main(['--source-root', str(src), '--machine-paths', str(paths)])
    assert '/home/u' not in (handoff / 'templates' / (inst.PROFILE + '.template')).read_text()

    # the new machine: different paths, real files for some pins only
    repo, home, data, env = (tmp_path / 'new' / n for n in ('repo', 'home', 'data', 'env'))
    model = write(repo / 'm.gguf', 'model')
    write(home / 'local-assets/y.pt', 'weights')
    write(data / 's.glb', 'scene')
    write(env / 'bin/python', 'py')
    write(repo / 'tax.json', '{}')
    write(repo / 'runs/lib/libhydra.so', 'so')
    monkeypatch.setattr(inst, 'TEMPLATES', handoff / 'templates')
    values = {'@REPO@': str(repo), '@NSN_HOME@': str(home), '@HABITAT_DATA@': str(data), '@HABITAT_ENV@': str(env)}
    written, report = inst.install(values, repo)
    status = {where: s for where, _, s in report.rows}
    assert status['slm.model'] == 'changed' and status['slm.runtime'] == 'MISSING'
    assert status['detector.openvino_model'] == 'MISSING' and status['tour.scene'] == 'changed'
    slm = json.loads((repo / inst.SLM).read_text())
    assert slm['model_path'] == str(model) and slm['model_sha256'] == sha(model)
    assert slm['runtime_sha256'] == 'c' * 64                                   # missing keeps the old pin
    ds = (repo / inst.HYDRA_DATASET).read_text()
    assert str(repo / 'runs/lib/libhydra.so') in ds and sha(repo / 'runs/lib/libhydra.so') in ds
    prof = json.loads((repo / inst.PROFILE).read_text())
    assert prof['scene_graph']['hydra']['dataset_sha256'] == sha(repo / inst.HYDRA_DATASET)
    assert prof['ui']['room_label_debug']['config_sha256'] == sha(repo / inst.SLM)
    assert prof['workers']['sensor']['python']['path'] == str(env / 'bin/python')
    assert prof['floor']['datum_source'] == 'measured:%s/.runtime/cal.json' % home
    with pytest.raises(SystemExit):                                          # no silent overwrite
        write(repo / inst.TOUR, 'edited')
        inst.install(values, repo)
    written, report = inst.install(values, repo, backend='torch', force=True)
    prof = json.loads((repo / inst.PROFILE).read_text())
    assert prof['detector']['backend'] == 'torch' and 'openvino_model' not in prof['detector']
    assert 'detector.openvino_model' not in {w for w, _, _ in report.rows}
    cpu_profile = (repo / inst.PROFILE).read_bytes()
    cpu_slm = (repo / inst.SLM).read_bytes()
    runtime = write(repo / 'llama-server-vulkan', 'vulkan runtime')
    inst.install(values, repo, backend='torch', force=True, slm_vulkan_runtime=runtime)
    gpu = json.loads((repo / inst.GPU_PROFILE).read_text())
    slm = json.loads((repo / inst.GPU_SLM).read_text())
    assert gpu['detector']['device'] == 'cuda:0'
    assert gpu['ui']['room_label_debug']['config_sha256'] == sha(repo / inst.GPU_SLM)
    assert slm['gpu_device'] == 'Vulkan0' and slm['runtime_sha256'] == sha(runtime)
    assert (repo / inst.PROFILE).read_bytes() == cpu_profile
    assert (repo / inst.SLM).read_bytes() == cpu_slm


def test_render_refuses_unresolved_placeholders():
    inst = _load('install')
    with pytest.raises(SystemExit):
        inst.render('@REPO@/@OTHER@', {k: '/x' for k in inst.PLACEHOLDERS})
