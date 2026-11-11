"""Optional UI-child setup. No runtime/controller import or external model access."""
from pathlib import Path
import hashlib,json
from ..contracts.observations import Taxonomy
from .slm_backend import RoomSlmBackendConfig
from .service import RoomLabelDebugService

DEBUG_ASSET_KEYS=frozenset({'config_path','config_sha256','taxonomy_path','taxonomy_sha256'})


def validate_debug_options(options):
    if not isinstance(options,dict) or set(options)!=DEBUG_ASSET_KEYS:raise ValueError('explicit pinned room_label_debug assets required')
    for kind in ('config','taxonomy'):
        p=Path(options[kind+'_path']);digest=options[kind+'_sha256']
        if not p.is_absolute() or not p.is_file() or p.stat().st_size>65536:raise ValueError('bounded absolute debug '+kind+' asset required')
        if not isinstance(digest,str) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('room_label_debug '+kind+' hash mismatch')
    return options


class UnavailableRoomLabelService:
    current_graph=None
    def __init__(self,error):self.error=str(error)[:512]
    def records(self):return ()
    def offer(self,graph):self.current_graph=graph;return False
    def status(self):return {'error':self.error,'pending':0,'in_flight':0,'experimental':True,'world_epoch':None}
    def close(self,timeout_s=3):return {'clean_shutdown':True,'disabled_reason':self.error}


def create_debug_service(options,*,artifact_root=None):
    try:
        validate_debug_options(options)
        config=RoomSlmBackendConfig.from_json(options['config_path'])
        if not config.enabled:raise ValueError('room label model config is disabled')
        data=json.loads(Path(options['taxonomy_path']).read_text())
        if data.get('schema_version')!=1:raise ValueError('unsupported debug taxonomy')
        taxonomy=Taxonomy(data['vocabulary_id'],tuple(data['categories']),data.get('aliases',{}),data['provenance'])
        from .persistent_backend import PersistentRoomLabelBackend
        return RoomLabelDebugService(PersistentRoomLabelBackend(config),taxonomy,artifact_root=artifact_root)
    except Exception as exc:return UnavailableRoomLabelService(f'{type(exc).__name__}: {exc}')
