"""Bounded, best-effort telemetry. Producers never perform I/O, sort or wait.

This is an in-memory primitive, not native evidence by itself. Caller stops all
producers before ``stop`` and serializes ``finalize`` off the control lane.
A failed try-record must not change admission, TTL or motion safety decisions.
"""
from dataclasses import asdict, dataclass
import math
import json
import re
from threading import Lock

from neusymnav.contracts import FrameKey

MAX_SAMPLES = 65_536
# Closed record fields/string/integer limits below keep compact UTF-8 JSON below
# this conservative charge, even with JSON's worst-case string escaping.
TRACE_RECORD_CHARGE = 8_192
CAPTURE_RECORD_CHARGE = 8_192
CONTEXT_CHARGE = 32_768
DISTRIBUTION_SAMPLE_CHARGE = 64
MAX_TRACE_BYTES = 512 * 1024 * 1024
MAX_INTEGER = (1 << 63) - 1
TIMING_STAGES = frozenset({
    'sensor_primary_roundtrip', 'sensor_navigation_roundtrip',
    'sensor_primary_decode', 'sensor_navigation_decode',
    'sensor_worker_dispatch', 'sensor_worker_handler', 'sensor_draw_observations',
    'sensor_readback_observations', 'sensor_packet_normalize_encode',
    'actuation_roundtrip', 'simulator_step', 'simulator_action', 'simulator_physics_step',
    'navmap_update', 'navmap_publish', 'navmap_overview_refresh', 'navmap_room_input',
    'navmap_prepare', 'navmap_integrate_raycast', 'navmap_core_integrate',
    'navmap_projection', 'navmap_raycast', 'navmap_vote_integration', 'navmap_retention',
    'navmap_core_snapshot_publish',
    'navmap_fresh_coverage', 'navmap_snapshot', 'navmap_overview_snapshot',
    'navmap_tile_overview', 'control_navigation_wait', 'control_loop',
    'local_depth_map', 'local_path_follow', 'local_motion_guard', 'world_navigation_intent',
})


def _integer(value, name, maximum=MAX_INTEGER, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value


def _text(value, name, maximum=128):
    if type(value) is not str or not 1 <= len(value) <= maximum:
        raise ValueError(f'{name} must be a nonempty string of at most {maximum} characters')
    # Encoding is bounded by the character guard and cannot dispatch a subclass
    # method after the exact-builtin check. Reject invalid Unicode as well.
    if len(value.encode('utf-8')) > maximum*4:
        raise ValueError(f'{name} exceeds UTF-8 byte quota')
    return value


def _hash(value, name):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError(f'{name} must be lowercase SHA-256')
    return value


def _navigation_diagnostics(value):
    keys={'goal_id','goal_xy','path_point_count','path_sample_xy','path_sample_truncated',
          'lookahead_xy','heading_error_rad','decision_reason'}
    if type(value) is not dict or set(value) not in (keys, keys|{'control_map_scope','world_intent'}):
        raise ValueError('navigation diagnostics fields mismatch')
    local='control_map_scope' in value
    world=None
    if local:
        if type(value['control_map_scope']) is not str or value['control_map_scope']!='local_measured_depth_v1':
            raise ValueError('unsupported control map scope')
        raw=value['world_intent']
        if raw is not None:
            fields={'source','capture_monotonic_ns','clock_domain','map_revision',
                    'created_monotonic_ns','valid_until_monotonic_ns'}
            if type(raw) is not dict or set(raw)!=fields:
                raise ValueError('world intent fields mismatch')
            key=raw['source']
            if type(key) is not dict or set(key)!={'episode_id','sensor_id','frame_index'}:
                raise ValueError('world intent source mismatch')
            _text(key['episode_id'],'intent episode');_text(key['sensor_id'],'intent sensor')
            _integer(key['frame_index'],'intent frame')
            _text(raw['clock_domain'],'intent clock')
            for name in fields-{'source','clock_domain'}:_integer(raw[name],name)
            if not (raw['capture_monotonic_ns']<=raw['created_monotonic_ns']<=raw['valid_until_monotonic_ns']
                    <=raw['capture_monotonic_ns']+2_000_000_000):
                raise ValueError('world intent time bounds mismatch')
            world=dict(raw,source=dict(key))
    goal_id=value['goal_id']
    if goal_id is not None:_text(goal_id,'goal_id')
    decision_reason=value['decision_reason'];_text(decision_reason,'decision_reason')
    def point(raw,name):
        if raw is None:return None
        if type(raw) not in (list,tuple) or len(raw)!=2:
            raise ValueError(name+' must be an XY pair or null')
        result=[]
        for item in raw:
            if type(item) not in (int,float) or not math.isfinite(item) or abs(item)>1_000_000:
                raise ValueError(name+' must contain bounded finite values')
            result.append(float(item))
        return result
    count=value['path_point_count'];_integer(count,'path_point_count',1_000_000)
    samples=value['path_sample_xy']
    if type(samples) is not list or len(samples)>64 or len(samples)>count:
        raise ValueError('path sample must contain at most 64 points within the full path')
    points=[point(item,'path_sample_xy') for item in samples]
    truncated=value['path_sample_truncated']
    if type(truncated) is not bool or truncated!=(count>len(points)):
        raise ValueError('path truncation flag must match sampled path size')
    heading=value['heading_error_rad']
    if heading is not None and (type(heading) not in (int,float) or not math.isfinite(heading)
                                or abs(heading)>math.pi+1e-6):
        raise ValueError('heading_error_rad must be a wrapped finite angle or null')
    result=dict(schema_version=2 if local else 1,goal_id=goal_id,goal_xy=point(value['goal_xy'],'goal_xy'),
        path_point_count=count,path_sample_xy=points,path_sample_truncated=truncated,
        lookahead_xy=point(value['lookahead_xy'],'lookahead_xy'),
        heading_error_rad=None if heading is None else float(heading),
        decision_reason=decision_reason)
    if local:
        if world is None and (goal_id is not None or count!=0):
            raise ValueError('null intent requires stopped path')
        result.update(control_map_scope='local_measured_depth_v1',world_intent=world)
    return result


def _navigation_binding(navigation,source,now_ns,context,captures,diagnostics):
    # Bind separate planning provenance without treating it as motion proof.
    if navigation is None or navigation['schema_version']!=2:return
    world=navigation['world_intent']
    if world is None:
        if diagnostics is not None and any(diagnostics[name] not in (None,0,0.) for name in
                ('decision_linear_mps','decision_yaw_radps','command_linear_mps','command_yaw_radps')):
            raise ValueError('null world intent cannot command motion')
        return
    key=FrameKey(**world['source'])
    registered=captures(key)
    if (source is None or key.episode_id!=context.episode_id or key.sensor_id not in context.sensor_ids
            or world['clock_domain']!=context.clock_domain or registered is None
            or registered.capture_monotonic_ns!=world['capture_monotonic_ns']
            or registered.clock_domain!=world['clock_domain']
            or world['capture_monotonic_ns']>source.capture_monotonic_ns
            or world['created_monotonic_ns']>now_ns):
        raise ValueError('world intent execution/source binding mismatch')


@dataclass(frozen=True, slots=True)
class MeasurementContext:
    attempt_id: str
    episode_id: str
    clock_domain: str
    config_sha256: str
    launch_config_sha256: str
    seed_ack_sha256: str | None
    sensor_ids: tuple[str, ...]
    schema_version: str = 'runtime_measurement_context_v1'

    def __post_init__(self):
        if type(self.schema_version) is not str or self.schema_version != 'runtime_measurement_context_v1':
            raise ValueError('unsupported measurement context schema')
        for name in ('attempt_id', 'episode_id', 'clock_domain'):
            _text(getattr(self, name), name)
        for name in ('config_sha256', 'launch_config_sha256'):
            _hash(getattr(self, name), name)
        if self.seed_ack_sha256 is not None:
            _hash(self.seed_ack_sha256, 'seed_ack_sha256')
        if type(self.sensor_ids) is not tuple or not 1 <= len(self.sensor_ids) <= 8:
            raise ValueError('sensor_ids must be a tuple of 1..8 declared sensors')
        for sensor_id in self.sensor_ids:
            _text(sensor_id, 'sensor_id')
        if len(set(self.sensor_ids)) != len(self.sensor_ids):
            raise ValueError('duplicate sensor_ids')


@dataclass(frozen=True, slots=True)
class MeasurementSource:
    key: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    pose_version: int
    calibration_id: str
    schema_version: str = 'runtime_measurement_source_v1'

    def __post_init__(self):
        if (type(self.schema_version) is not str or self.schema_version != 'runtime_measurement_source_v1'
                or type(self.key) is not FrameKey):
            raise ValueError('unsupported measurement source schema/key')
        _text(self.key.episode_id, 'episode_id')
        _text(self.key.sensor_id, 'sensor_id')
        _integer(self.key.frame_index, 'frame_index')
        _integer(self.capture_monotonic_ns, 'capture_monotonic_ns')
        _integer(self.pose_version, 'pose_version')
        _text(self.clock_domain, 'clock_domain')
        _text(self.calibration_id, 'calibration_id')


class _Distribution:
    def __init__(self, cap):
        self.cap = cap
        self.samples = []
        self.seen = 0
        self.counter_saturated = False

    def record(self, value):
        if self.seen == MAX_INTEGER:
            self.counter_saturated = True
            return False
        self.seen += 1
        if len(self.samples) < self.cap:
            self.samples.append(value)
            return True
        return False

    def finalize(self):
        overflow = self.seen - len(self.samples)
        result = dict(seen=self.seen, retained=len(self.samples), overflow=overflow,
                      p50=None, p95=None, reason=None)
        if self.counter_saturated:
            result['reason'] = 'counter_saturated'
        elif overflow:
            result['reason'] = 'sample_overflow'
        elif not self.samples:
            result['reason'] = 'no_samples'
        else:
            ordered = sorted(self.samples)
            def quantile(fraction):
                position = (len(ordered)-1)*fraction
                low = math.floor(position)
                high = math.ceil(position)
                return float(ordered[low] + (ordered[high]-ordered[low])*(position-low))
            result.update(p50=quantile(.5), p95=quantile(.95))
        return result


class BoundedMeasurements:
    """One execution context; bounded capture registry and closed scalar trace.

    Producer calls are O(1) with fixed validation/record limits. They use try-lock;
    contention drops are accounted with CPython's atomic ``next(range_iterator)``.
    No arbitrary callbacks or payload objects run while holding the collector lock.
    Trace byte accounting is a conservative serialization quota, not Python RSS.
    ``finalize`` owns sorting/copying after producers have stopped.
    """
    def __init__(self, context, *, sample_cap=MAX_SAMPLES,
                 trace_byte_cap=8 * 1024 * 1024, capture_cap=MAX_SAMPLES):
        if type(context) is not MeasurementContext:
            raise ValueError('MeasurementContext required')
        _integer(sample_cap, 'sample_cap', MAX_SAMPLES, 1)
        _integer(capture_cap, 'capture_cap', MAX_SAMPLES, 1)
        _integer(trace_byte_cap, 'trace_byte_cap', MAX_TRACE_BYTES)
        self.context = context
        self.sample_cap = sample_cap
        self.trace_byte_cap = trace_byte_cap
        self.capture_cap = capture_cap
        self._lock = Lock()
        self._contention = iter(range(MAX_INTEGER))
        self._contention_reads = 0
        self._counter_saturated = False
        self._stopped = False
        self._captures = {}
        self._watermarks = {}
        self._capture_overflow = 0
        self._rejected = 0
        self._trace = []
        self._trace_dropped = 0
        self._distributions = {name: _Distribution(sample_cap) for name in (
            'capture_to_detector_return_ns', 'capture_to_object_commit_ns', 'control_depth_age_ns')}
        self._excluded = dict(historical=0, reused=0, recovery=0)
        self._admissions = dict(offered=0, durable_accepted=0, rejected=0, replaced=0, stale=0)
        # Finite distinct reasons: a new reason after cap is rejected/incomplete.
        self._reasons = {}
        self._last_control_ns = None

    def _source(self, source, *, registered=True):
        if type(source) is not MeasurementSource:
            raise ValueError('MeasurementSource required')
        key = source.key
        if type(key) is not FrameKey:
            raise ValueError('FrameKey required')
        # FrameKey is frozen but has a mutable __dict__. Own a fresh closed copy;
        # validate snapshotted raw builtins BEFORE calling its shared constructor
        # (which calls .strip/int and accepts subclasses). No caller methods or
        # unbounded text scans may execute under this producer lock.
        episode_id, sensor_id, frame_index = key.episode_id, key.sensor_id, key.frame_index
        capture_ns, domain = source.capture_monotonic_ns, source.clock_domain
        pose_version, calibration_id, schema = source.pose_version, source.calibration_id, source.schema_version
        for name, value in (('episode_id',episode_id), ('sensor_id',sensor_id),
                            ('clock_domain',domain), ('calibration_id',calibration_id),
                            ('schema_version',schema)):
            _text(value, name)
        _integer(frame_index, 'frame_index')
        _integer(capture_ns, 'capture_monotonic_ns')
        _integer(pose_version, 'pose_version')
        if schema != 'runtime_measurement_source_v1':
            raise ValueError('unsupported measurement source schema')
        source = MeasurementSource(FrameKey(episode_id, sensor_id, frame_index),
                                   capture_ns, domain, pose_version, calibration_id, schema)
        if (source.key.episode_id != self.context.episode_id or
                source.clock_domain != self.context.clock_domain or
                source.key.sensor_id not in self.context.sensor_ids):
            raise ValueError('source execution/clock/sensor mismatch')
        if registered:
            entry = self._captures.get(source.key)
            if entry is None or entry[0] != source:
                raise ValueError('source must match registered capture exactly')
            return entry
        return source

    def _try(self, action):
        if not self._lock.acquire(blocking=False):
            next(self._contention, MAX_INTEGER)
            return False
        try:
            if self._stopped:
                return False
            try:
                accepted = action()
            except (ValueError, TypeError):
                self._bump_attr('_rejected')
                return False
            return accepted is not False and not self._counter_saturated
        finally:
            self._lock.release()

    def _bump_attr(self, name):
        value = getattr(self, name)
        if value == MAX_INTEGER:
            self._counter_saturated = True
        else:
            setattr(self, name, value+1)

    def _bump(self, counts, name):
        value = counts.get(name, 0)
        if value == MAX_INTEGER:
            self._counter_saturated = True
        else:
            counts[name] = value+1

    def _trace_record(self, event, source, **fields):
        if (len(self._trace)+1)*TRACE_RECORD_CHARGE > self.trace_byte_cap:
            self._bump_attr('_trace_dropped')
            return False
        # Navigation records may carry at most 64 bounded XY path samples.
        self._trace.append(dict(event=event, source=asdict(source) if source is not None else None, **fields))
        return True

    def try_record_capture(self, source, *, width, height):
        def record():
            owned = self._source(source, registered=False)
            _integer(width, 'width', 65_536, 1)
            _integer(height, 'height', 65_536, 1)
            previous = self._watermarks.get(owned.key.sensor_id)
            if previous and (owned.key.frame_index <= previous[0] or
                             owned.capture_monotonic_ns < previous[1]):
                raise ValueError('capture frame/time watermark cannot go backward or reset')
            if len(self._captures) >= self.capture_cap:
                self._bump_attr('_capture_overflow')
                raise ValueError('capture registry overflow')
            self._captures[owned.key] = (owned, width, height, {})
            self._watermarks[owned.key.sensor_id] = (owned.key.frame_index, owned.capture_monotonic_ns)
            return self._trace_record('capture', owned, width=width, height=height)
        return self._try(record)

    def try_record_result(self, source, *, now_ns, clock_domain, kind, origin='live', revision=None):
        def record():
            entry = self._source(source)
            owned = entry[0]
            _integer(now_ns, 'now_ns')
            if type(clock_domain) is not str or clock_domain != self.context.clock_domain:
                raise ValueError('measurement clock mismatch')
            if now_ns < owned.capture_monotonic_ns:
                raise ValueError('negative latency')
            if type(kind) is not str or kind not in ('detector_return', 'object_commit'):
                raise ValueError('unknown result kind')
            if type(origin) is not str or origin not in ('live', 'historical', 'reused', 'recovery'):
                raise ValueError('unknown result origin')
            if revision is not None:
                _integer(revision, 'revision')
            if kind == 'object_commit' and revision is None:
                raise ValueError('object commit requires owner revision')
            retained = True
            if origin != 'live':
                self._bump(self._excluded, origin)
            else:
                if kind in entry[3]:
                    raise ValueError('duplicate live result')
                detector_at = entry[3].get('detector_return')
                commit_at = entry[3].get('object_commit')
                if ((kind == 'object_commit' and detector_at is not None and now_ns < detector_at) or
                        (kind == 'detector_return' and commit_at is not None and now_ns > commit_at)):
                    raise ValueError('object commit precedes detector return')
                entry[3][kind] = now_ns
                retained = self._distributions['capture_to_'+kind+'_ns'].record(now_ns-owned.capture_monotonic_ns)
            traced = self._trace_record(kind, owned, now_ns=now_ns, origin=origin, revision=revision)
            return retained and traced
        return self._try(record)

    def try_record_control(self, source, *, now_ns, clock_domain, reason, map_revision,
                           diagnostics=None,navigation_diagnostics=None):
        def record():
            owned = None if source is None else self._source(source)[0]
            _integer(now_ns, 'now_ns')
            if type(clock_domain) is not str or clock_domain != self.context.clock_domain:
                raise ValueError('measurement clock mismatch')
            _integer(map_revision, 'map_revision')
            _text(reason, 'reason')
            if owned is not None and now_ns < owned.capture_monotonic_ns:
                raise ValueError('negative depth age')
            if self._last_control_ns is not None and now_ns < self._last_control_ns:
                raise ValueError('control clock cannot go backward')
            if reason not in self._reasons and len(self._reasons) >= 128:
                raise ValueError('reason vocabulary overflow')
            if diagnostics is not None:
                keys={'decision_reason','decision_linear_mps','decision_yaw_radps',
                      'command_reason','command_linear_mps','command_yaw_radps',
                      'command_issued_monotonic_ns','command_deadline_monotonic_ns',
                      'failure_detail'}
                if type(diagnostics) is not dict or set(diagnostics)!=keys:
                    raise ValueError('control diagnostics fields mismatch')
                for name in ('decision_reason','command_reason'):
                    value=diagnostics[name]
                    if value is not None:_text(value,name)
                for name in ('decision_linear_mps','decision_yaw_radps','command_linear_mps','command_yaw_radps'):
                    value=diagnostics[name]
                    if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e3):
                        raise ValueError(name+' must be a bounded finite number or null')
                for name in ('command_issued_monotonic_ns','command_deadline_monotonic_ns'):
                    value=diagnostics[name]
                    if value is not None:_integer(value,name)
                detail=diagnostics['failure_detail']
                if detail is not None and detail not in ('deadline_expired','zero_motion_command'):
                    raise ValueError('unknown actuator failure detail')
            navigation=None if navigation_diagnostics is None else _navigation_diagnostics(navigation_diagnostics)
            if navigation is not None and navigation['schema_version']==2:
                # Only v2 records need the extra quota check; legacy closed shape
                # is already conservatively bounded by TRACE_RECORD_CHARGE.
                _navigation_binding(navigation,owned,now_ns,self.context,
                    lambda key: self._captures[key][0] if key in self._captures else None,diagnostics)
                candidate=dict(event='control',source=None if owned is None else asdict(owned),
                    now_ns=now_ns,reason=reason,map_revision=map_revision,
                    depth_age_ns=None if owned is None else now_ns-owned.capture_monotonic_ns,
                    navigation=navigation)
                if diagnostics is not None:candidate['diagnostics']=dict(diagnostics)
                if len(json.dumps(candidate,ensure_ascii=True,allow_nan=False).encode())>TRACE_RECORD_CHARGE:
                    raise ValueError('v2 control record exceeds charged byte quota')
            self._bump(self._reasons, reason)
            self._last_control_ns = now_ns
            age = None if owned is None else now_ns-owned.capture_monotonic_ns
            retained = True
            if age is not None:
                retained = self._distributions['control_depth_age_ns'].record(age)
            fields=dict(now_ns=now_ns,reason=reason,map_revision=map_revision,depth_age_ns=age)
            if diagnostics is not None:fields['diagnostics']=dict(diagnostics)
            if navigation is not None:fields['navigation']=navigation
            traced = self._trace_record('control', owned, **fields)
            return retained and traced
        return self._try(record)

    def try_record_admission(self, source, *, outcome):
        def record():
            owned = self._source(source)[0]
            if type(outcome) is not str or outcome not in self._admissions:
                raise ValueError('unknown admission outcome')
            self._bump(self._admissions, outcome)
            return self._trace_record('admission', owned, outcome=outcome)
        return self._try(record)

    def try_record_stage(self, source, *, stage, start_ns, end_ns, clock_domain):
        """Record one source-bound monotonic stage interval as diagnostics only."""
        def record():
            owned = self._source(source)[0]
            if type(stage) is not str or stage not in TIMING_STAGES:
                raise ValueError('unknown timing stage')
            _integer(start_ns, 'start_ns')
            _integer(end_ns, 'end_ns')
            if end_ns < start_ns:
                raise ValueError('timing stage end precedes start')
            if type(clock_domain) is not str or clock_domain != owned.clock_domain:
                raise ValueError('timing stage clock mismatch')
            return self._trace_record('stage', owned, stage=stage, start_ns=start_ns,
                                      end_ns=end_ns, duration_ns=end_ns-start_ns)
        return self._try(record)

    def stop(self):
        """Call off control after producer shutdown. This method can wait for a producer."""
        with self._lock:
            self._stopped = True

    def finalize(self):
        """No I/O. Return a detached JSON-compatible snapshot after stop only."""
        with self._lock:
            if not self._stopped:
                raise RuntimeError('stop producers and collector before finalize')
            # Observe atomic count without resetting it; subtract our own reads.
            contention_token = next(self._contention, MAX_INTEGER)
            contention = contention_token - self._contention_reads
            self._contention_reads = min(MAX_INTEGER, self._contention_reads+1)
            saturated = (self._counter_saturated or contention_token == MAX_INTEGER or
                         any(d.counter_saturated for d in self._distributions.values()))
            distributions = {key: value.finalize() for key, value in self._distributions.items()}
            complete = not (saturated or contention or self._rejected or self._capture_overflow or
                            self._trace_dropped or any(d['overflow'] for d in distributions.values()))
            # asdict/deepcopy happens only here or on fixed scalar records at record time.
            import copy
            return dict(schema_version='runtime_measurements_primitive_v1', context=asdict(self.context),
                        native_eligible_context=False, native_eligibility_status='not_evaluated_by_primitive',
                        seed_ack_bound=self.context.seed_ack_sha256 is not None,
                        evidence_scope='caller_supplied_context_and_registered_capture_records',
                        complete=complete, rejected_records=self._rejected, contention_dropped=contention,
                        counter_saturated=saturated,
                        distributions=distributions, excluded_results=dict(self._excluded),
                        admission_counts=dict(self._admissions),
                        admission_semantics='event_counts; offered denominator; outcomes may overlap across stages',
                        control_reasons=dict(self._reasons),
                        capture_registry=dict(cap=self.capture_cap, retained=len(self._captures), overflow=self._capture_overflow,
                                              record_charge_bytes=CAPTURE_RECORD_CHARGE,
                                              byte_cap=self.capture_cap*CAPTURE_RECORD_CHARGE,
                                              charged_bytes=len(self._captures)*CAPTURE_RECORD_CHARGE),
                        storage_budget=dict(context_charge_bytes=CONTEXT_CHARGE,
                                            distribution_sample_charge_bytes=DISTRIBUTION_SAMPLE_CHARGE,
                                            distribution_byte_cap=3*self.sample_cap*DISTRIBUTION_SAMPLE_CHARGE,
                                            source_text_max_characters=128, source_text_max_utf8_bytes=512,
                                            accounting='fixed conservative quotas, not a measured RSS bound'),
                        trace=dict(schema_version='runtime_measurement_trace_v1', records=copy.deepcopy(self._trace),
                                   byte_cap=self.trace_byte_cap, record_charge_bytes=TRACE_RECORD_CHARGE,
                                   charged_bytes=len(self._trace)*TRACE_RECORD_CHARGE, dropped=self._trace_dropped,
                                   storage='bounded_memory', writer_pending=False),
                        travel=dict(body_translation_m=None, frontier_translation_m=None,
                                    reason='strict_native_body_actuation_proof_unavailable'),
                        no_progress=dict(intervals=None, reason='strict_native_body_actuation_proof_unavailable'))
