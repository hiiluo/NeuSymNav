from test_runtime_measurement_wiring import session,source


def test_retention_stage_preserves_source_and_duration_in_measurements():
    m=session();obs=source()
    assert m.capture(obs)
    assert m.stage(obs,'navmap_retention',110,175)
    result=m.finalize(runtime_report={'clean_shutdown':True},resources=None)
    records=[x for x in result['collector']['trace']['records'] if x['event']=='stage']
    assert records[0]['stage']=='navmap_retention'
    assert records[0]['duration_ns']==65
    assert records[0]['source']['key']['frame_index']==obs.key.frame_index
