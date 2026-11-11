"""Local memory retention is exported as diagnostic, never fresh motion proof."""
from test_runtime_scheduling import pipeline


def test_pipeline_reports_detached_mapper_retention_summary(tmp_path):
    class Mapper:
        @property
        def retention_diagnostics(self):
            return {'policy':'rolling_local_v1','radius_m':2.,'retention_s':10.,
                    'resident_tiles':4,'timestamp_bytes':1024}
        def close(self,timeout_s=1.):return {'clean_shutdown':True}
    p,_,_=pipeline(tmp_path,mapper=Mapper())
    try:
        diagnostic=p.telemetry()['navmap_retention']
        assert diagnostic['retention_s']==10.
        assert diagnostic['timestamp_bytes']==1024
        diagnostic['retention_s']=999
        assert p.telemetry()['navmap_retention']['retention_s']==10.
    finally:p.close(2.)
