"""Durable committed-evidence consumer; never writes the canonical object ledger.

NewOH3DSG verification thresholds and quality recipes are retained. Unique
accepted rows, camera independence and consumption decisions live in a separate
SQLite database, replacing the source's unbounded in-memory event dictionaries.
All methods belong to the same graph thread as the configured ObjectOwner.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import fcntl
import io
import json
import math
from pathlib import Path
import sqlite3
from time import monotonic_ns
from types import MappingProxyType
from uuid import uuid4
from ..contracts.graphs import CommitResult
from ..contracts.observations import FrameKey, validate_detection_batch
from ..contracts.serialization import loads
from ..objects.ledger import canonical
from .best_views import BestView, BestViewSelector
from .negative import current_source, validate_negative
import numpy as np


@dataclass(frozen=True)
class VerificationRequest:
    id: str
    episode_id: str
    object_id: str
    source_revision: int
    deadline_ns: int


@dataclass(frozen=True)
class VerifierResult:
    request_id: str
    episode_id: str
    object_id: str
    source_revision: int
    decision: str
    label: str | None = None

    def __post_init__(self):
        if self.decision not in {'confirmed','conflict','timeout','failed'}:
            raise ValueError('unsupported verifier decision')


@dataclass(frozen=True)
class ObjectVerification:
    object_id: str
    object_revision: int
    graph_lifecycle: str
    status: str
    label: str | None
    detected_count: int
    independent_views: int
    negative_views: int
    negative_history_count: int
    accepted_negative_history_count: int
    evidence_alpha: float
    evidence_beta: float
    reason: str
    best_views: tuple[BestView, ...]


@dataclass(frozen=True)
class VerificationSnapshot:
    episode_id: str
    object_revision: int
    objects: object
    aliases: object
    batch_count: int
    complete_empty_batch_count: int
    view_count: int
    negative_history_count: int
    replay_required: bool
    rejection_reasons: object


class VerificationOwner:
    MIN_DETECTIONS = 5
    MIN_VIEWS = 3
    MIN_LABEL_SUPPORT = .8
    MIN_VIEW_BASELINE_M = .3
    MAX_NEGATIVE_VIEWS = 16

    def __init__(self, object_owner, *, clock_domain, now_ns=monotonic_ns, root=None):
        if not isinstance(clock_domain, str) or not clock_domain or not callable(now_ns):
            raise ValueError('verification requires clock identity and provider')
        self.owner = object_owner
        self.clock_domain, self._now_ns = clock_domain, now_ns
        self.root = Path(root) if root is not None else object_owner.ledger.root / 'verification'
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = (self.root / 'owner.lock').open('a+b')
        self._db = None
        self._pending = {}
        self._negative_epoch = str(uuid4())
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._db = sqlite3.connect(self.root / 'verification.sqlite3', isolation_level=None)
            self._db.row_factory = sqlite3.Row
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.execute('PRAGMA synchronous=FULL')
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('unsupported verification schema; explicit migration required')
            self._db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches(event_id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS views(event_id TEXT PRIMARY KEY,object_id TEXT,
                    kind TEXT NOT NULL,label TEXT NOT NULL,x REAL,y REAL,z REAL,
                    quality REAL,independent INTEGER NOT NULL,data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS object_views ON views(object_id,independent);
                CREATE TABLE IF NOT EXISTS negatives(event_id TEXT PRIMARY KEY,object_id TEXT,
                    accepted INTEGER NOT NULL,reason TEXT NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions(object_id TEXT PRIMARY KEY,
                    object_revision INTEGER NOT NULL,evidence_revision INTEGER NOT NULL,
                    status TEXT NOT NULL,retry_after_ns INTEGER NOT NULL);
                PRAGMA user_version=1;
            ''')
            config = canonical(dict(object_config=json.loads(object_owner.ledger.get('config')),
                recipe='new-verification-5-3-080-baseline030:v1',clock_domain=clock_domain))
            prior = self._db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
            if prior is not None and prior[0] != config:
                raise ValueError('verification episode/profile/clock mismatch')
            self._db.execute("INSERT OR IGNORE INTO metadata VALUES ('config',?)", (config,))
            if self._db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('verification integrity check failed')

        except BaseException:
            self.close()
            raise

    def _rows(self, table, event_ids=None):
        """Stream committed owner rows; no all-history Python event-ID set."""
        conn = self.owner.ledger.connection
        if event_ids is None:
            cursor = conn.execute(f'SELECT * FROM {table} ORDER BY rowid')
            for row in cursor:
                value = json.loads(row['data'])
                value.update({key: row[key] for key in row.keys() if key != 'data'})
                yield value
        else:
            # A commit is bounded by the admitted detector payload. Each lookup
            # uses the unique event index rather than scanning ledger history.
            for event_id in event_ids:
                row = conn.execute(f'SELECT * FROM {table} WHERE event_id=?', (event_id,)).fetchone()
                if row is not None:
                    value = json.loads(row['data'])
                    value.update({key: row[key] for key in row.keys() if key != 'data'})
                    yield value

    def _sync_aliases(self, snapshot):
        changed = False
        for old, target in snapshot.aliases.items():
            canonical_id = snapshot.resolve_id(target)
            for table in ('views', 'negatives'):
                changed |= self._db.execute(f'UPDATE {table} SET object_id=? WHERE object_id=?',
                    (canonical_id, old)).rowcount > 0
        if changed:
            # Recompute independence in original accepted row order after union.
            self._db.execute('UPDATE views SET independent=0')
            for row in self._db.execute("SELECT * FROM views WHERE kind='detected' ORDER BY rowid"):
                if row['object_id'] is not None and self._independent(row['object_id'], (row['x'],row['y'],row['z'])):
                    self._db.execute('UPDATE views SET independent=1 WHERE event_id=?',(row['event_id'],))

    def _independent(self, object_id, camera):
        x,y,z = camera
        return self._db.execute('''SELECT 1 FROM views WHERE object_id=? AND independent=1
            AND ((x-?)*(x-?)+(y-?)*(y-?)+(z-?)*(z-?)) < ? LIMIT 1''',
            (object_id,x,x,y,y,z,z,self.MIN_VIEW_BASELINE_M**2)).fetchone() is None

    def _source(self, record):
        source = loads(self.owner.assets.read(record['source_asset']).decode())
        batch = loads(self.owner.assets.read(record['batch_asset']).decode())
        validate_detection_batch(source,batch)
        if (record['source'] != dict(episode_id=source.key.episode_id,
            sensor_id=source.key.sensor_id,frame_index=source.key.frame_index)
            or record['geometry_hash'] != source.geometry_hash):
            raise ValueError('committed verification source/geometry mismatch')
        return source,batch

    def _view(self, record, snapshot):
        if self._db.execute('SELECT 1 FROM views WHERE event_id=?',(record['event_id'],)).fetchone():
            return
        object_id = record['object_id']
        if object_id is not None:
            object_id = snapshot.resolve_id(object_id)
        source,batch = self._source(record)
        detection = next(d for d in batch.detections if d.detection_id == record['detection_id'])
        mask = np.load(io.BytesIO(self.owner.assets.read(record['mask_asset'])),allow_pickle=False)
        self.owner.assets.read(record['crop_asset'])
        if not np.array_equal(mask,detection.mask):
            raise ValueError('committed verification mask mismatch')
        # Source Fusion._view: measured depth fraction, mask/box occupancy.
        ys,xs = np.nonzero(mask)
        depth_quality = float(np.count_nonzero(mask & source.valid_depth
            & (source.depth_m >= .15) & (source.depth_m < 5.)) / np.count_nonzero(mask))
        mask_quality = float(np.count_nonzero(mask) / ((int(ys.max())-int(ys.min())+1)
            *(int(xs.max())-int(xs.min())+1)))
        camera = tuple(float(v) for v in source.T_world_camera[:3,3])
        if record['camera_position'] != list(camera) or record['score'] != detection.score:
            raise ValueError('committed verification camera/score mismatch')
        quality = record['score'] * depth_quality * mask_quality
        record = dict(record,depth_quality=depth_quality,mask_quality=mask_quality,quality=quality)
        independent = (object_id is not None and record['evidence_kind']=='detected'
            and self._independent(object_id,camera))
        self._db.execute('INSERT INTO views VALUES (?,?,?,?,?,?,?,?,?,?)',
            (record['event_id'],object_id,record['evidence_kind'],record['category'] or record['raw_label'],
             *camera,quality,int(independent),canonical(record)))

    def _negative(self, record, snapshot, *, replay):
        if self._db.execute('SELECT 1 FROM negatives WHERE event_id=?',(record['event_id'],)).fetchone():
            return
        batch = self.owner.ledger.batch(record['batch_key'])
        batch_record = json.loads(batch['data'])
        source, detection_batch = self._source(record)
        reason = validate_negative(record,batch_record,source,detection_batch,snapshot)
        # The final freshness read occurs after reads/checksum/decode/geometry work.
        if reason is None and (replay or not current_source(record,
            now_ns=self._now_ns(),clock_domain=self.clock_domain)):
            reason = 'historical_or_expired'
        self._db.execute('INSERT INTO negatives VALUES (?,?,?,?,?)',
            (record['event_id'],snapshot.aliases.get(record['object_id'],record['object_id']),
             int(reason is None),'accepted_current' if reason is None else reason,canonical(dict(record,consumer_epoch=self._negative_epoch))))

    def _consume(self, snapshot, event_ids, *, replay):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            self._sync_aliases(snapshot)
            for record in self._rows('batches',event_ids):
                self._db.execute('INSERT OR IGNORE INTO batches VALUES (?,?)',
                    (record['event_id'],canonical(record)))
            for record in self._rows('views',event_ids):
                self._view(record,snapshot)
            for record in self._rows('negatives',event_ids):
                self._negative(record,snapshot,replay=replay)
            self._db.execute("INSERT INTO metadata VALUES ('object_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(snapshot.revision),))
            self._db.execute('COMMIT')
        except BaseException:
            self._db.execute('ROLLBACK')
            raise

    def consume(self, commit: CommitResult) -> None:
        self._consume_commit(commit, historical=False)

    def consume_historical(self, commit: CommitResult) -> None:
        """ACK recovered committed evidence without granting live negatives."""
        self._consume_commit(commit, historical=True)

    def _consume_commit(self, commit, *, historical):
        if not isinstance(commit,CommitResult):
            raise ValueError('verification requires CommitResult')
        snapshot = self.owner.snapshot()
        if commit.snapshot.episode_id != snapshot.episode_id or commit.snapshot.revision > snapshot.revision:
            raise ValueError('verification commit episode/revision mismatch')
        self._consume(snapshot,commit.committed_event_ids,replay=historical)
        for oid,(request,evidence_revision) in tuple(self._pending.items()):
            if (oid not in snapshot.objects or snapshot.objects[oid].revision!=request.source_revision
                or self._evidence_revision(oid)!=evidence_revision):
                self._pending.pop(oid,None)

    def replay(self) -> None:
        """Explicitly recover missing accepted history. Never revive negatives.

        Already consumed decisions stay idempotent; missing negative records are
        retained as history with current credit suppressed even on a live clock.
        """
        self._negative_epoch = str(uuid4())
        self._consume(self.owner.snapshot(),None,replay=True)

    def _evidence_revision(self, object_id):
        return sum(self._db.execute(f'SELECT count(*) FROM {table} WHERE object_id=?',
            (object_id,)).fetchone()[0] for table in ('views','negatives'))

    def request(self, object_id):
        """Optional async verifier seam, pinned to canonical geometry + evidence."""
        object_id = self.resolve_id(object_id)
        snapshot = self.snapshot()
        state = snapshot.objects[object_id]
        now = self._now_ns()
        if (snapshot.replay_required or state.detected_count == 0 or state.status == 'verified'
            or object_id in self._pending):
            return None
        decision = self._db.execute('SELECT * FROM decisions WHERE object_id=?',(object_id,)).fetchone()
        if decision is not None and now < decision['retry_after_ns']:
            return None
        request = VerificationRequest(str(uuid4()),snapshot.episode_id,object_id,
            state.object_revision,now+10_000_000_000)
        self._pending[object_id] = (request,self._evidence_revision(object_id))
        return request

    def apply_result(self, result: VerifierResult):
        if not isinstance(result,VerifierResult):
            raise ValueError('verifier result type mismatch')
        canonical_id = self.resolve_id(result.object_id)
        pending = self._pending.get(canonical_id)
        current = self.owner.snapshot()
        if (canonical_id != result.object_id or pending is None
            or result.episode_id != current.episode_id
            or result.request_id != pending[0].id):
            raise ValueError('verifier result does not match pending canonical request')
        request,evidence_revision = pending
        if (result.source_revision != request.source_revision
            or current.objects[canonical_id].revision != request.source_revision
            or self._evidence_revision(canonical_id) != evidence_revision):
            self._pending.pop(canonical_id,None)
            raise ValueError('stale verifier object/evidence revision')
        now = self._now_ns()
        decision = 'timeout' if now > request.deadline_ns else result.decision
        state = self.snapshot().objects[canonical_id]
        status = state.status
        retry_after = 0
        if decision in {'timeout','failed'}:
            status = 'unknown'
            retry_after = max(now,request.deadline_ns)+30_000_000_000
        elif decision == 'conflict':
            status = 'tracked'
        elif result.label is not None and result.label != state.label:
            status = 'tracked'
        # Confirmation cannot promote beyond the independent detector criteria.
        self._db.execute('INSERT INTO decisions VALUES (?,?,?,?,?) ON CONFLICT(object_id) '
            'DO UPDATE SET object_revision=excluded.object_revision,evidence_revision=excluded.evidence_revision,'
            'status=excluded.status,retry_after_ns=excluded.retry_after_ns',
            (canonical_id,request.source_revision,evidence_revision,status,retry_after))
        self._pending.pop(canonical_id,None)
        return self.snapshot().objects[canonical_id]

    def expire(self):
        now = self._now_ns()
        for request,_ in tuple(self._pending.values()):
            if now > request.deadline_ns:
                try:
                    self.apply_result(VerifierResult(request.id,request.episode_id,
                        request.object_id,request.source_revision,'timeout'))
                except ValueError:
                    self._pending.pop(request.object_id,None)

    def resolve_id(self, object_id):
        return self.owner.resolve_id(object_id)

    @staticmethod
    def _best(row, object_id):
        r=json.loads(row['data'])
        return BestView(object_id,r['event_id'],FrameKey(**r['source']),r['detection_id'],
            r['capture_monotonic_ns'],r['clock_domain'],r['geometry_hash'],r['object_revision'],
            tuple(r['camera_position']),r['quality'],r['score'],r['depth_quality'],r['mask_quality'],
            r['crop_asset'],r['mask_asset'],r['source_asset'],tuple(r['crop_bbox_xyxy']))

    def best_views(self, object_id=None):
        if object_id is None:
            return tuple(view for oid in self.owner.snapshot().objects for view in self.best_views(oid))
        object_id = self.resolve_id(object_id)
        gallery = BestViewSelector(object_id)
        for row in self._db.execute("SELECT * FROM views WHERE object_id=? AND kind='detected' ORDER BY rowid",(object_id,)):
            gallery.offer(self._best(row,object_id))
        return gallery.snapshot()

    def _current_negatives(self, object_id, revision, now):
        cameras=[]; sources=[]
        for row in self._db.execute('SELECT * FROM negatives WHERE object_id=? AND accepted=1 ORDER BY rowid',(object_id,)):
            r=json.loads(row['data'])
            if (r.get('consumer_epoch') != self._negative_epoch or r['object_revision'] != revision
                or not current_source(r,now_ns=now,clock_domain=self.clock_domain)):
                continue
            camera=tuple(r['camera_position'])
            if all(math.dist(camera,c)>=self.MIN_VIEW_BASELINE_M for c in cameras):
                sources.append(r)
                if len(cameras) == self.MAX_NEGATIVE_VIEWS:
                    return len(cameras),True,tuple(sources)
                cameras.append(camera)
        return len(cameras),False,tuple(sources)

    def snapshot(self):
        snapshot=self.owner.snapshot()
        now=self._now_ns()
        # Counts detect dropped/failed consumption without retaining event sets.
        ledger=self.owner.ledger.connection
        missing=any(ledger.execute(f'SELECT count(*) FROM {table}').fetchone()[0]!=
            self._db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in ('batches','views','negatives'))
        watermark=self._db.execute("SELECT value FROM metadata WHERE key='object_revision'").fetchone()
        missing |= (watermark is None and snapshot.revision!=0) or (watermark is not None and int(watermark[0])!=snapshot.revision)
        objects={}; negative_sources={}
        for oid,obj in snapshot.objects.items():
            counts=self._db.execute('''SELECT count(*),coalesce(sum(independent),0),
                coalesce(sum(CASE WHEN independent=1 THEN quality ELSE 0 END),0)
                FROM views WHERE object_id=? AND kind='detected' ''',(oid,)).fetchone()
            count,positive,quality=counts
            label_row=self._db.execute("SELECT label,count(*) n FROM views WHERE object_id=? AND kind='detected' GROUP BY label ORDER BY n DESC,min(rowid) LIMIT 1",(oid,)).fetchone()
            label=None if label_row is None else label_row[0]
            qualifies=count>=5 and positive>=3 and label_row[1]/count>=.8
            negative,incomplete,sources=self._current_negatives(oid,obj.revision,now)
            negative_sources[oid]=sources
            history,accepted=self._db.execute('SELECT count(*),coalesce(sum(accepted),0) FROM negatives WHERE object_id=?',(oid,)).fetchone()
            status='unknown' if incomplete else ('verified' if qualifies else ('tracked' if count>=2 else 'candidate'))
            reason='negative_view_cap' if incomplete else ('multiview_label_support' if qualifies else 'insufficient_independent_detector_support')
            decision=self._db.execute('SELECT * FROM decisions WHERE object_id=?',(oid,)).fetchone()
            if (decision is not None and decision['object_revision']==obj.revision
                and decision['evidence_revision']==self._evidence_revision(oid)):
                status=decision['status']
                reason='async_verifier_'+status
            if missing:
                status,reason='unknown','replay_required'
            objects[oid]=ObjectVerification(oid,obj.revision,obj.lifecycle,status,label,count,positive,
                negative,history,accepted,1.+quality,1.+positive-quality+(negative if negative>=3 else 0),
                reason,self.best_views(oid))
        batch_count=self._db.execute('SELECT count(*) FROM batches').fetchone()[0]
        empty=sum(1 for row in self._db.execute('SELECT data FROM batches') if
            (lambda r:r['completion']=='complete' and not r['detections'])(json.loads(row[0])))
        views=self._db.execute('SELECT count(*) FROM views').fetchone()[0]
        negatives=self._db.execute('SELECT count(*) FROM negatives').fetchone()[0]
        reasons=dict(self._db.execute('SELECT reason,count(*) FROM negatives WHERE accepted=0 GROUP BY reason').fetchall())
        # No SQL, assets or gallery work after this boundary. Retain at most
        # MAX_NEGATIVE_VIEWS+1 proofs per object, then expire credit against the
        # actual return-time clock, including time spent on later objects.
        # If an earlier view expired, a previously occluded-by-baseline view
        # might qualify; we conservatively undercount until the next snapshot
        # rather than keeping history-sized buffers or renewing old credit.
        final_now=self._now_ns()
        for oid,state in objects.items():
            count=min(self.MAX_NEGATIVE_VIEWS,sum(current_source(r,now_ns=final_now,
                clock_domain=self.clock_domain) for r in negative_sources[oid]))
            if count != state.negative_views:
                old_credit=state.negative_views if state.negative_views>=3 else 0
                new_credit=count if count>=3 else 0
                objects[oid]=replace(state,negative_views=count,
                    evidence_beta=state.evidence_beta-old_credit+new_credit)
        return VerificationSnapshot(snapshot.episode_id,snapshot.revision,MappingProxyType(objects),
            MappingProxyType(dict(snapshot.aliases)),batch_count,empty,views,negatives,missing,
            MappingProxyType(reasons))

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db=None
        if not self._lock.closed:
            fcntl.flock(self._lock.fileno(),fcntl.LOCK_UN)
            self._lock.close()
