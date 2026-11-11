"""Diagnostic entry: actual stable pipeline, bounded lightweight per-revision export.

No sensor, policy, motion or native algorithm change. Does not read annotations.
"""
from pathlib import Path
import copy, hashlib, json, os, sys, time
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'src'))
from neusymnav.backends.hydra import worker
BaseOwner=worker._PipelineOwner
class ObservedOwner(BaseOwner):
    def process_frame(self,frame):
        started=time.monotonic_ns()
        result=super().process_frame(frame)
        finished=time.monotonic_ns()
        if not result.get('accepted'):return result
        directory=self.artifact_dir.parent.parent/'room-revisions'
        directory.mkdir(parents=True,exist_ok=True)
        summary=copy.deepcopy(result['graph_summary'])
        graph=self.pipeline.graph
        distances={str(n.id):float(n.attributes.distance) for layer in graph.layers if int(layer.id)==3 for n in layer.nodes}
        for node in summary['nodes']:
            if node['native_id'] in distances:node['clearance_m']=distances[node['native_id']]
        pairs=sorted([[n['native_id'],n.get('parent_native_id')] for n in summary['nodes'] if n['layer_id']==3])
        value={'schema_version':1,'scope':'actual_native_after_accepted_step_no_reconstruction',
            'episode_id':frame.source_key.episode_id,'sensor_id':frame.source_key.sensor_id,
            'frame_index':frame.source_key.frame_index,'capture_monotonic_ns':frame.capture_monotonic_ns,
            'clock_domain':frame.clock_domain,'calibration_hash':frame.calibration_hash,
            'source_geometry_hash':frame.source_geometry_hash,'graph_revision':self.graph_revision,
            'input_prefix_sha256':self.input_prefix,'summary':summary,
            'native_metadata':result.get('native_metadata'),
            'room_stability_diagnostics':result.get('room_stability_diagnostics'),
            'place_membership_pairs':pairs,'place_membership_sha256':hashlib.sha256(json.dumps(pairs,separators=(',',':'),ensure_ascii=True).encode()).hexdigest(),
            'native_process_including_summary_ms':(finished-started)/1e6,
            'loaded_hydra_library_maps':[s.strip() for s in Path('/proc/self/maps').read_text().splitlines() if '/libhydra.so' in s],
            'rss_observed_bytes':int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')}
        literal=json.dumps(value,sort_keys=True,allow_nan=False).encode()
        self._diagnostic_bytes=getattr(self,'_diagnostic_bytes',0)+len(literal)
        if len(literal)>2*1024*1024 or self._diagnostic_bytes>128*1024*1024:
            raise RuntimeError('bounded room diagnostic export exhausted')
        temporary=directory/f'{self.graph_revision:04d}.tmp'
        temporary.write_bytes(literal)
        temporary.replace(directory/f'{self.graph_revision:04d}.json')
        return result
worker._PipelineOwner=ObservedOwner
if __name__=='__main__':raise SystemExit(worker.main())
