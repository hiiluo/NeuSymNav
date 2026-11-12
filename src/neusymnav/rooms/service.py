"""UI-process-only asynchronous room labeling."""
from collections import OrderedDict
from dataclasses import replace,fields,is_dataclass
from pathlib import Path
from collections.abc import Mapping
import json,threading,time,math
from ..backends.hydra.graph_adapter import HydraGraphProjection
from ..contracts.room_semantics import RoomLabelProposal,validate_room_label
from .debug_context import build_debug_jobs
from .debug_types import RoomLabelDebugRecord
from .evidence_quality import assess_evidence_quality

MAX_PENDING=32;MAX_HISTORY=128;MAX_HISTORY_BYTES=8*1024*1024;MAX_RECORD_BYTES=256*1024
MAX_SEMANTIC_CACHE=256;WRITE_INTERVAL_NS=1_000_000_000
# Model answers worth reusing; transport failures/timeouts are retried instead.
_CACHEABLE_RESULTS=frozenset({'available','unknown','insufficient_evidence'})


def semantic_key(request):
    """Identity of the text evidence for one room.

    Hydra's display snapshot hash changes whenever any node anywhere moves, so
    it cannot decide whether a room needs a new label. The model input is only
    this room's object rows. The visual path adds its ordered image IDs.
    """
    k=request.key;c=request.context
    return (k.episode_id,k.run_id,k.world_epoch,k.room_id,c.geometry_status,c.truncated,
        tuple((o.native_id,o.category,o.membership_status) for o in c.objects))


def _plain(x):
    if is_dataclass(x):return {f.name:_plain(getattr(x,f.name)) for f in fields(x)}
    if isinstance(x,Mapping):return {str(k):_plain(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)):return [_plain(v) for v in x]
    if x is None or isinstance(x,(str,int,float,bool)):return x
    raise TypeError('unsupported debug record data')


def _identity(g):
    if g is None:return None
    source=g.native_metadata.get('room_label_input') or {}
    return (g.episode_id,g.run_id,g.graph_revision,g.input_prefix_sha256,g.status,g.stale,g.replay_required,g.native_metadata.get('graph_world_epoch'),source.get('snapshot_sha256'))


class RoomLabelDebugService:
    def __init__(self,backend,taxonomy,*,artifact_root=None,now_ns=time.monotonic_ns,
                 debounce_s=3.,room_view_selector=None):
        if not 0<=debounce_s<=60:raise ValueError('invalid debug debounce')
        self.backend=backend;self.taxonomy=taxonomy;self._now=now_ns;self._debounce_ns=int(debounce_s*1e9)
        self._room_view_selector = room_view_selector
        self._cv=threading.Condition();self._latest=None;self._offered_ns=0;self._closed=False
        self._generation=0;self._processed=None;self._pending=OrderedDict();self._history=OrderedDict();self._history_bytes=0
        self._active=None;self._infer_thread=None;self._finished=None;self._last_room='';self._dispatch_times={}
        self._scope=None;self._reset=False;self._version=0
        self._semantic=OrderedDict();self._reuse_index={};self._last_write_ns=None
        self._last_vlm_labels = {}
        self._status={'offered_graphs':0,'coalesced_graphs':0,'completed':0,'cancelled':0,'evicted':0,'error':None,'experimental':True,
            'semantic_cache_hits':0,'model_inferences':0,'warmup':None,
            'label_backend':'vlm' if room_view_selector is not None else 'slm'}
        self._root=None if artifact_root is None else Path(artifact_root)
        if self._root:self._root.mkdir(parents=True,exist_ok=True)
        self._worker=threading.Thread(target=self._run,name='room-label-debug-manager',daemon=True);self._worker.start()
        self._warm_thread=None
        if callable(getattr(backend,'warm',None)):
            self._warm_thread=threading.Thread(target=self._warm,name='room-label-warmup',daemon=True);self._warm_thread.start()

    def _warm(self):
        try:report=self.backend.warm()
        except Exception as exc:report={'warmed':False,'reason':f'{type(exc).__name__}: {exc}'[:256]}
        try:plain=_plain(report) if isinstance(report,Mapping) else None
        except TypeError:plain={'warmed':bool(report.get('warmed')),'reason':'unserializable warmup report'}
        with self._cv:
            self._status['warmup']=plain;self._version+=1;self._cv.notify_all()

    @property
    def current_graph(self):
        with self._cv:return self._latest

    def offer(self,graph):
        if graph is not None and not isinstance(graph,HydraGraphProjection):raise TypeError('typed graph required')
        with self._cv:
            if self._closed:return False
            if _identity(graph)==_identity(self._latest):return False
            scope=None if graph is None else (graph.episode_id,graph.run_id,graph.native_metadata.get('graph_world_epoch'))
            if scope!=self._scope:
                self._generation+=1;self._reset=self._reset or self._scope is not None or self._active is not None;self._processed=None;self._pending.clear();self._history.clear();self._history_bytes=0;self._dispatch_times.clear();self._last_room=''
                self._semantic.clear();self._reuse_index.clear()
                self._last_vlm_labels.clear()
                self._scope=scope
            if self._last_vlm_labels and graph.status == 'available' and not graph.stale and not graph.replay_required:
                room_ids = {node.node_id for node in graph.nodes if node.layer_id == 4}
                self._last_vlm_labels = {room: label for room, label in self._last_vlm_labels.items()
                                         if room in room_ids}
            self._status['coalesced_graphs']+=len(self._pending);self._pending.clear();self._processed=None
            self._latest=graph;self._offered_ns=self._now();self._status['offered_graphs']+=1;self._version+=1;self._cv.notify_all()
            return True

    def records(self):
        with self._cv:
            records=list(reversed([v[0] for v in self._history.values()]))
            if self._active:records.insert(0,self._active[0])
            records.extend(RoomLabelDebugRecord(j,'pending',evidence_quality=assess_evidence_quality(j.request.context)) for j in self._pending.values())
            return tuple(records[:MAX_HISTORY+MAX_PENDING+1])

    def status(self):
        with self._cv:return {**self._status,'pending':len(self._pending),'in_flight':int(self._active is not None),'history':len(self._history),'history_bytes':self._history_bytes,'version':self._version,'closed':self._closed,'world_epoch':None if self._latest is None else self._latest.native_metadata.get('graph_world_epoch')}

    def retained_vlm_labels(self, graph):
        """Return previously classified labels for display within the current graph scope."""
        if graph is None:
            return {}
        scope = (graph.episode_id, graph.run_id, graph.native_metadata.get('graph_world_epoch'))
        with self._cv:
            if scope != self._scope:
                return {}
            return {room: label for room, label in self._last_vlm_labels.items()
                    if label.geometry_revision <= graph.graph_revision}

    def _append(self,record):
        size=len(json.dumps(_plain(record),ensure_ascii=True,separators=(',',':')).encode())
        if size>MAX_RECORD_BYTES:self._status['error']='source record exceeds debug byte cap';self._status['evicted']+=1;return
        key=record.job.request.request_id
        if key in self._history:self._history_bytes-=self._history.pop(key)[1]
        self._history[key]=(record,size);self._history_bytes+=size
        while len(self._history)>MAX_HISTORY or self._history_bytes>MAX_HISTORY_BYTES:
            _,(_,oldsize)=self._history.popitem(last=False);self._history_bytes-=oldsize;self._status['evicted']+=1
        self._version+=1

    def _infer(self,record,generation,source_graph):
        try:
            request = record.job.request
            views = ()
            if self._room_view_selector is None:
                proposal = self.backend.infer(request)
                metrics = dict(getattr(self.backend, 'last_metrics', {}))
            else:
                started = self._now()
                views = self._room_view_selector(source_graph, request.key.room_id)
                selection_ms = (self._now() - started) / 1e6
                key = (*semantic_key(request), tuple(view.view_id for view in views))
                with self._cv:
                    if self._closed or generation != self._generation:
                        if not self._closed:
                            self._finished = (record, generation)
                            self._cv.notify_all()
                        return
                    cached = self._semantic.get(key)
                if cached is not None:
                    source, source_id, source_revision = cached
                    status = 'proposed' if source.status == 'available' else source.status
                    proposal = RoomLabelProposal(request.key.room_id, request.key.graph_revision,
                        request.key.context_hash, source.label, source.alternatives,
                        source.supporting_object_ids, status, source.reason, source.model_sha256,
                        source.prompt_sha256, source.supporting_view_ids)
                    metrics = {'semantic_cache': 'hit', 'reused_from_request_id': source_id,
                               'reused_from_revision': source_revision, 'model_called': False}
                elif not views and (request.inference_block_reason
                                  or record.evidence_quality['only_generic_objects']):
                    reason = request.inference_block_reason or 'non_discriminating_object_context'
                    proposal = RoomLabelProposal(request.key.room_id, request.key.graph_revision,
                        request.key.context_hash, 'unknown', (), (), 'insufficient_evidence', reason, None, None)
                    metrics = {'model_called': False}
                else:
                    proposal = self.backend.infer(request, views=views)
                    metrics = dict(getattr(self.backend, 'last_metrics', {}))
                    metrics['model_called'] = True
                metrics.update(label_backend='vlm', room_view_selection_ms=selection_ms,
                               room_views=[view.manifest() for view in views])
            result = validate_room_label(proposal, request.context,
                                         allowed_view_ids=tuple(view.view_id for view in views))
            completed=replace(record,state='complete',result=result,completed_ns=self._now(),backend_metrics=metrics)
        except Exception as exc:
            completed=replace(record,state='error',completed_ns=self._now(),error=f'{type(exc).__name__}: {exc}'[:512])
        with self._cv:
            if not self._closed:self._finished=(completed,generation)
            self._cv.notify_all()

    def _remember(self,record):
        result=record.result
        if result is None or result.status not in _CACHEABLE_RESULTS or result.model_sha256 is None:return
        key=semantic_key(record.job.request)
        if self._room_view_selector is not None:
            # A cached answer for old evidence must not replace a later model result.
            if record.backend_metrics.get('semantic_cache') == 'hit':
                return
            graph = self._latest
            previous = self._last_vlm_labels.get(result.room_id)
            if (result.status == 'available' and graph is not None
                    and result.geometry_revision <= graph.graph_revision
                    and (previous is None or result.geometry_revision >= previous.geometry_revision)
                    and any(node.layer_id == 4 and node.node_id == result.room_id for node in graph.nodes)):
                self._last_vlm_labels[result.room_id] = result
            views = record.backend_metrics.get('room_views', ())
            key = (*key, tuple(view['view_id'] for view in views))
        self._semantic[key]=(result,record.job.request.request_id,record.job.request.key.graph_revision)
        self._semantic.move_to_end(key)
        while len(self._semantic)>MAX_SEMANTIC_CACHE:self._semantic.popitem(last=False)

    def _resolve_cached_locked(self):
        """Attach remembered answers to newer revisions whose room rows are unchanged."""
        for room,job in list(self._pending.items()):
            key=semantic_key(job.request)
            hit=self._semantic.get(key)
            if hit is None:continue
            source,source_id,source_revision=hit;q=job.request
            status='proposed' if source.status=='available' else source.status
            proposal=RoomLabelProposal(q.key.room_id,q.key.graph_revision,q.key.context_hash,source.label,
                source.alternatives,source.supporting_object_ids,status,source.reason,source.model_sha256,source.prompt_sha256)
            stamp=self._now()
            record=RoomLabelDebugRecord(job,'complete',result=validate_room_label(proposal,q.context),started_ns=stamp,completed_ns=stamp,
                backend_metrics={'semantic_cache':'hit','reused_from_request_id':source_id,'reused_from_revision':source_revision,'latency_ms':0.0},
                evidence_quality=assess_evidence_quality(q.context))
            del self._pending[room]
            index=(q.key.room_id,key);previous=self._reuse_index.get(index)
            if previous is not None and previous in self._history:
                self._history_bytes-=self._history.pop(previous)[1]
            self._append(record)
            if q.request_id in self._history:self._reuse_index[index]=q.request_id
            self._status['completed']+=1;self._status['semantic_cache_hits']+=1

    def _write(self):
        if self._root is None:return
        try:
            # Snapshot under lock; serialization and IO outside it.
            with self._cv:records=[v[0] for v in self._history.values()];status=self.status()
            payload=json.dumps({'schema_version':1,'kind':'experimental_room_label_snapshot_history','status':status,'records':_plain(records)},ensure_ascii=True,separators=(',',':')).encode()
            if len(payload)>MAX_HISTORY_BYTES+65536:raise ValueError('debug report byte cap exceeded')
            temp=self._root/'history.tmp';temp.write_bytes(payload);temp.replace(self._root/'history.json')
        except Exception as exc:
            with self._cv:self._status['artifact_error']=f'{type(exc).__name__}: {exc}'[:256]

    def _run(self):
        written=-1
        while True:
            with self._cv:
                if self._closed:break
                reset=self._reset;self._reset=False
                graph=self._latest;identity=_identity(graph);gen=self._generation;offered=self._offered_ns
                if self._finished is not None:
                    record,oldgen=self._finished;self._finished=None;self._active=None
                    if oldgen==gen:
                        self._append(record);self._status['completed']+=1
                        self._status['model_inferences'] += int(record.backend_metrics.get('model_called', True))
                        self._status['semantic_cache_hits'] += int(record.backend_metrics.get('semantic_cache') == 'hit')
                        self._remember(record)
                    else:self._status['cancelled']+=1
                active=self._active
            if reset:
                # This manager is never the Qt/control thread.
                try:self.backend.cancel()
                except Exception as exc:
                    with self._cv:self._status['error']='cancel: '+str(exc)[:256]
            if graph is not None and identity!=self._processed:
                try:jobs=build_debug_jobs(graph,self.taxonomy,offered);error=None
                except Exception as exc:jobs=();error=f'{type(exc).__name__}: {exc}'[:512]
                with self._cv:
                    if gen==self._generation and identity==_identity(self._latest):
                        self._processed=identity;self._status['error']=error
                        activekey=None if self._active is None else self._active[0].job.request.request_id
                        latest=OrderedDict((j.request.key.room_id,j) for j in jobs if j.request.request_id!=activekey and j.request.request_id not in self._history)
                        self._status['coalesced_graphs']+=len(self._pending)
                        self._pending=latest;self._version+=1
            with self._cv:
                # No second inferthread until previous one has fully returned.
                free=self._active is None and (self._infer_thread is None or not self._infer_thread.is_alive())
                eligible=sorted(k for k in self._pending if self._now()-self._dispatch_times.get(k,-10**30)>=self._debounce_ns)
                if not self._closed and not self._reset and self._processed==_identity(self._latest):
                    self._resolve_cached_locked()
                    eligible=[k for k in eligible if k in self._pending]
                if free and eligible and not self._closed and not self._reset and self._processed==_identity(self._latest):
                    key=next((k for k in eligible if k>self._last_room),eligible[0]);job=self._pending.pop(key)
                    stamp=self._now();self._last_room=key;self._dispatch_times[key]=stamp;gen=self._generation
                    quality=assess_evidence_quality(job.request.context)
                    record=RoomLabelDebugRecord(job,'running',started_ns=stamp,evidence_quality=quality,
                        backend_metrics={'label_backend':self._status['label_backend']})
                    blocked=job.request.inference_block_reason
                    if self._room_view_selector is not None and blocked == 'no_semantic_objects':
                        blocked = None
                    if self._room_view_selector is None and quality['only_generic_objects']:
                        blocked='non_discriminating_object_context'
                    if blocked:
                        q=job.request;proposal=RoomLabelProposal(q.key.room_id,q.key.graph_revision,q.key.context_hash,'unknown',(),(),'insufficient_evidence',blocked,None,None)
                        self._append(replace(record,state='complete',completed_ns=self._now(),result=validate_room_label(proposal,q.context)))
                        self._status['completed']+=1
                    else:
                        self._active=(record,gen);self._version+=1
                        self._infer_thread=threading.Thread(target=self._infer,args=(record,gen,graph),name='room-label-debug-infer',daemon=True);self._infer_thread.start()
                version=self._version
            now=self._now()
            if version!=written and (self._last_write_ns is None or now-self._last_write_ns>=WRITE_INTERVAL_NS):
                self._write();written=version;self._last_write_ns=now
            with self._cv:
                if not self._closed:self._cv.wait(.05)
        self._write()

    def close(self,timeout_s=3):
        if isinstance(timeout_s,bool) or not isinstance(timeout_s,(int,float)) or not math.isfinite(timeout_s) or timeout_s<=0:raise ValueError('positive finite shutdown timeout required')
        deadline=time.monotonic()+timeout_s
        with self._cv:self._closed=True;self._pending.clear();self._generation+=1;self._cv.notify_all()
        try:backend_report=self.backend.close(max(.001,deadline-time.monotonic()))
        except Exception as exc:backend_report={'clean_shutdown':False,'error':str(exc)[:256]}
        self._worker.join(max(0,deadline-time.monotonic()))
        thread=self._infer_thread
        if thread:thread.join(max(0,deadline-time.monotonic()))
        warm=self._warm_thread
        if warm:warm.join(max(0,deadline-time.monotonic()))
        with self._cv:
            if self._active:
                record,_=self._active
                self._append(replace(record,state='cancelled',completed_ns=self._now(),error='debug service shutdown'))
                self._active=None;self._status['cancelled']+=1
            self._finished=None
        report={'clean_shutdown':bool(backend_report.get('clean_shutdown')) and not self._worker.is_alive() and not(thread and thread.is_alive()),'backend':backend_report,'worker_pending':self._worker.is_alive() or bool(thread and thread.is_alive()) or bool(warm and warm.is_alive())}
        self._write()
        if self._root:
            (self._root/'shutdown.json').write_text(json.dumps(report))
        return report
