#!/usr/bin/env python3
"""Run a matched offline control-cadence A/B with UI disabled/enabled."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from neusymnav.runtime.launcher import replay_control_cadence
from neusymnav.runtime.replay_control import assert_ab_profiles_differ_only_by_ui_enabled


def _load(path):
    return json.loads(Path(path).read_text())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--measurements',required=True)
    parser.add_argument('--ui-off-config',required=True)
    parser.add_argument('--ui-on-config',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--duration-s',type=float,default=15.)
    parser.add_argument('--warmup-s',type=float,default=5.)
    args=parser.parse_args(argv)
    off=_load(args.ui_off_config);on=_load(args.ui_on_config)
    if off['ui'].get('enabled') is not False or on['ui'].get('enabled') is not True:
        raise ValueError('UI-off/UI-on profile flags are reversed or absent')
    assert_ab_profiles_differ_only_by_ui_enabled(off,on)
    root=Path(args.out).absolute()
    if root.exists() and any(root.iterdir()):raise ValueError('A/B output root must be empty')
    root.mkdir(parents=True,exist_ok=True)
    common=dict(input_path=args.input,measurements_path=args.measurements,
        duration_s=args.duration_s,warmup_s=args.warmup_s)
    # Sequential execution preserves the single-native-workload invariant.
    result_off=replay_control_cadence(config_path=args.ui_off_config,out=root/'ui-off',**common)
    result_on=replay_control_cadence(config_path=args.ui_on_config,out=root/'ui-on',**common)
    summary=dict(schema_version=1,input_sha256=result_off['input_sha256'],
        profile_configs_identical_except_ui_enabled=True,arms={'ui_off':result_off,'ui_on':result_on})
    (root/'ab-summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps({name:{'outcome':value['outcome'],'ui_enabled':value['ui_enabled'],
        'control_invocations':value['control_invocations'],'control_interval':value['control_interval'],
        'control_results':value['control_results'],'control_status_counts':value['control_status_counts'],
        'source_run_control_results':value['source_run_control_results'],'navigation_wait':value['navigation_wait'],
        'actuator_calls':value['actuator_calls'],'error':value['error']}
        for name,value in summary['arms'].items()},indent=2,sort_keys=True))
    return 0 if all(value['outcome']=='completed' for value in summary['arms'].values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
