import json
import pytest
from test_evaluation_protocol import pin


def measured_bundle(tmp_path):
    from neusymnav.runtime.launcher import replay
    from pathlib import Path
    root=tmp_path/'export';fixture=Path(__file__).parent/'fixtures/package'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    summary=json.loads((root/'summary.json').read_text())
    from test_evaluation_measurements import artifact
    summary['config_sha256']=pin(fixture/'config.yaml')['sha256']
    value=artifact();value['context'].update(attempt_id=summary['attempt_id'],episode_id=summary['episode_id'],clock_domain=summary['runtime']['metrics']['configuration']['clock_domain'],config_sha256=summary['config_sha256'])
    # A completed replay cannot be relabelled as a coherent measured live run.
    # Use this fixture only to test exact v2 bundle presence/pins, not eligibility.
    (root/'measurements.json').write_text(json.dumps(value));summary['measurement_artifact']=dict(path='measurements.json',sha256=pin(root/'measurements.json')['sha256'])
    (root/'summary.json').write_text(json.dumps(summary))
    manifest=json.loads((root/'export-manifest.json').read_text());manifest['schema_version']=2
    manifest['files']['summary.json']=pin(root/'summary.json')['sha256'];manifest['files']['measurements.json']=pin(root/'measurements.json')['sha256']
    (root/'export-manifest.json').write_text(json.dumps(manifest))
    return root


def test_v2_bundle_requires_measurement_pin_before_runtime_integrity(tmp_path):
    from neusymnav.evaluation.exports import load_runtime_export
    root=measured_bundle(tmp_path)
    # New v2 parser should reach measurement consistency check, not reject version.
    with pytest.raises(ValueError,match='measurement|collector'):
        load_runtime_export(root/'export-manifest.json')


def test_v2_missing_measurement_has_exact_five_file_requirement(tmp_path):
    from neusymnav.evaluation.exports import load_runtime_export
    root=measured_bundle(tmp_path);path=root/'export-manifest.json';manifest=json.loads(path.read_text());manifest['files'].pop('measurements.json');path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='five-file'):load_runtime_export(path)
