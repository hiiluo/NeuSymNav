"""One episode-scoped object identity owner with atomic publication and recovery."""
from __future__ import annotations
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from threading import RLock
from time import monotonic_ns
import numpy as np
from ..contracts.observations import (AppearanceBatch, AppearanceFeature, FrameKey, age_ns,
    validate_object_observations)
from ..contracts.graphs import CommitResult, ObjectSnapshot, ObjectState
from ..contracts.serialization import dumps, loads
from .association import AssociationEngine, AssociationObservation
from .assets import AssetStore
from .ledger import Ledger, canonical
from .negative_evidence import negative_visibility
from .appearance import AGGREGATION_ID


def _digest(*parts):
    digest=hashlib.sha256()
    for part in parts:
        data=part.encode() if isinstance(part,str) else part
        digest.update(len(data).to_bytes(8,'big')); digest.update(data)
    return digest.hexdigest()


def _npy(value):
    stream=io.BytesIO(); np.save(stream,value,allow_pickle=False); return stream.getvalue()


class ObjectOwner:
    """Primary RGB-D object lane. Close explicitly or use a context manager.

    Profile, vocabulary and host boot clock identity are immutable per ledger.
    All source assets and masks/crops survive empty batches and process restart.
    ``now_ns`` must be in ``clock_domain``; replay domains are always historical.
    """
    def __init__(self, root, *, episode_id, primary_sensor_id, floor_id,
                 detector_profile_id, vocabulary_id, clock_domain, now_ns=monotonic_ns,
                 appearance_mode="off"):
        self._config=dict(episode_id=episode_id,primary_sensor_id=primary_sensor_id,
            floor_id=floor_id,detector_profile_id=detector_profile_id,
            vocabulary_id=vocabulary_id,clock_domain=clock_domain)
        if any(not isinstance(v,str) or not v.strip() for v in self._config.values()):
            raise ValueError('owner configuration identities must be nonempty strings')
        if not callable(now_ns): raise ValueError('now_ns must be a clock provider')
        if appearance_mode not in {'off','openclip'}:
            raise ValueError('appearance profile must be off or openclip')
        self.appearance_mode=appearance_mode
        self._now_ns=now_ns
        self._mutex=RLock()
        self.ledger=Ledger(root,self._config)
        try:
            profile=canonical(dict(schema_version=1,mode=appearance_mode,
                aggregation=AGGREGATION_ID,scoring='geometry-visual-030-020-010-020:v1'))
            previous=self.ledger.get('appearance_profile')
            # Existing schema1 P04 ledgers with no profile explicitly mean off.
            populated=self.ledger.get('checkpoint') is not None or self.ledger.connection.execute(
                'SELECT 1 FROM batches LIMIT 1').fetchone() is not None
            if (previous is not None and previous!=profile) or (previous is None and populated and appearance_mode!='off'):
                raise ValueError('appearance profile mismatch; explicit migration required')
            self.assets=AssetStore(Path(root)/'assets')
            self._engine=AssociationEngine(episode_id,association_mode=(
                'geometry_appearance' if appearance_mode=='openclip' else 'geometry'),
                event_lookup=self._lookup_event)
            self._snapshot=ObjectSnapshot(episode_id,0,FrameKey(episode_id,primary_sensor_id,0),{}, {})
            self.dispatch_watermark=-1
            self._capture_watermark=-1
            checkpoint=self.ledger.get('checkpoint')
            if checkpoint is not None:
                saved=json.loads(checkpoint)
                if set(saved)!={'schema_version','engine','snapshot','dispatch_watermark','capture_watermark'} or saved['schema_version']!=1:
                    raise ValueError('unsupported object checkpoint schema')
                self._snapshot=loads(saved['snapshot'])
                if not isinstance(self._snapshot,ObjectSnapshot) or self._snapshot.episode_id!=episode_id:
                    raise ValueError('checkpoint belongs to another episode')
                self._engine.restore_active_state(saved['engine'])
                self.dispatch_watermark=saved['dispatch_watermark']
                self._capture_watermark=saved['capture_watermark']
            for row in self.ledger.connection.execute('SELECT ref FROM assets'):
                self.assets.read(row[0])
            legacy = checkpoint is not None and any('visual_weight' not in raw for raw in saved['engine'].values())
            if legacy:
                self._restore_legacy_appearance()
            pinned_spec=self.ledger.get('appearance_spec')
            for track in self._engine._tracks.values():
                if track.visual_weight > track.detected_count:
                    raise ValueError('appearance checkpoint count exceeds accepted detection count')
                if track.visual_embedding is not None:
                    if pinned_spec is None or len(track.visual_embedding)!=json.loads(pinned_spec)['dimension']:
                        raise ValueError('appearance feature space/dimension mismatch')
            # Pin recipe only after recovery validation. Config/schema/evidence stay intact.
            conn=self.ledger.connection; conn.execute('BEGIN IMMEDIATE')
            try:
                if legacy:
                    self._checkpoint(self._engine,self._snapshot,self.dispatch_watermark,self._capture_watermark)
                    self.ledger.set('appearance_migration',canonical(dict(schema_version=1,
                        source='p04-schema1-last-feature',target=AGGREGATION_ID,
                        order='appearance-rowid',profile='off')))
                self.ledger.set('appearance_profile',profile)
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK'); raise
        except BaseException:
            self.ledger.close(); raise

    def _restore_legacy_appearance(self):
        """Explicit additive schema1 migration; all original evidence remains."""
        spec=self._appearance_spec_for(loads(row['payload']) for row in
            self.ledger.connection.execute('SELECT payload FROM appearances ORDER BY rowid'))
        for track in self._engine._tracks.values():
            track.visual_embedding=None; track.visual_weight=0
        for row in self.ledger.connection.execute(
                'SELECT a.object_id,a.payload,e.data FROM appearances a JOIN events e '
                'ON a.event_id=e.event_id ORDER BY a.rowid'):
            if row['object_id'] in self._engine._tracks and json.loads(row['data'])['evidence_kind']=='detected':
                self._engine.attach_visual(row['object_id'],loads(row['payload']).vector)
        objects=dict(self._snapshot.objects)
        space=None if spec is None else json.loads(spec)['space_id']
        for object_id,track in self._engine._tracks.items():
            objects[object_id]=replace(objects[object_id],appearance=(None if track.visual_embedding is None
                else AppearanceFeature(space,track.visual_embedding)),revision=self._snapshot.revision+1)
        self._snapshot=replace(self._snapshot,objects=objects,revision=self._snapshot.revision+1)

    def _aggregate_feature(self, track, spec):
        if track.visual_embedding is None:
            return None
        return AppearanceFeature(json.loads(spec)['space_id'],track.visual_embedding)

    def snapshot(self):
        with self._mutex:
            return self._snapshot

    def resolve_id(self, object_id):
        return self.snapshot().resolve_id(object_id)

    def _lookup_event(self, event_key):
        episode,index,detection,kind=event_key
        key=canonical([episode,self._config['primary_sensor_id'],index,
            self._config['detector_profile_id'],self._config['vocabulary_id']])
        event_id=_digest('object-evidence:v1',key,detection,kind)
        row=self.ledger.connection.execute('SELECT object_id,data FROM events WHERE event_id=?',
            (event_id,)).fetchone()
        return None if row is None else (row['object_id'],json.loads(row['data'])['association_digest'])

    def _checkpoint(self, engine, snapshot, watermark, capture_watermark):
        self.ledger.set('checkpoint',canonical(dict(schema_version=1,
            engine=engine.export_active_state(),snapshot=dumps(snapshot),
            dispatch_watermark=watermark,capture_watermark=capture_watermark)))

    def _appearance_spec_for(self, features):
        expected=self.ledger.get('appearance_spec')
        for feature in features:
            candidate=canonical(dict(space_id=feature.space_id,dimension=len(feature.vector)))
            if expected is not None and candidate!=expected:
                raise ValueError('appearance feature space/dimension mismatch')
            expected=candidate
        return expected

    def _validate_source(self, source, batch, observations):
        validate_object_observations(source,batch,observations)
        cfg=self._config
        if source.key.episode_id!=cfg['episode_id'] or source.key.sensor_id!=cfg['primary_sensor_id']:
            raise ValueError('object owner requires pinned episode and primary sensor')
        if source.clock_domain!=cfg['clock_domain'] or batch.vocabulary_id!=cfg['vocabulary_id']:
            raise ValueError('object owner clock/vocabulary mismatch')
        return age_ns(source.capture_monotonic_ns,source.clock_domain,self._now_ns(),cfg['clock_domain'])

    def _build_snapshot(self, engine, source, observations, ids, event_ids, *, aliases=None, appearance_spec=None):
        revision=self._snapshot.revision+1
        objects=dict(self._snapshot.objects)
        for id_, prior in list(objects.items()):
            if id_ not in engine._tracks and prior.lifecycle not in {'retired','merged'}:
                objects[id_]=replace(prior,lifecycle='retired',revision=revision)
        touched={id_ for id_ in ids if id_ is not None}
        for object_id,track in engine._tracks.items():
            prior=objects.get(object_id)
            indices=[i for i,value in enumerate(ids) if value==object_id]
            if object_id not in touched and prior is not None:
                if prior.lifecycle!=track.status:
                    objects[object_id]=replace(prior,lifecycle=track.status,revision=revision)
                continue
            item=observations[indices[-1]]
            cloud=track.points_world
            lower,upper=cloud.min(axis=0),cloud.max(axis=0)
            footprint=np.array([[lower[0],lower[1]],[upper[0],lower[1]],
                [upper[0],upper[1]],[lower[0],upper[1]]],float)
            stamp=source.capture_monotonic_ns
            refs=(() if prior is None else prior.evidence_refs)+tuple(event_ids[i] for i in indices)
            appearance=self._aggregate_feature(track,appearance_spec)
            objects[object_id]=ObjectState(object_id,self._config['floor_id'],
                np.median(cloud,axis=0),np.stack((lower,upper)),track.status,refs,revision,
                source.key if prior is None or stamp>=prior.last_seen_ns else prior.source,
                stamp if prior is None else min(prior.first_seen_ns,stamp),
                stamp if prior is None else max(prior.last_seen_ns,stamp),source.clock_domain,
                item.raw_label if prior is None or stamp>=prior.last_seen_ns else prior.raw_label,
                item.category if prior is None or stamp>=prior.last_seen_ns else prior.category,
                points_world=cloud,footprint_xy=footprint,appearance=appearance)
        return ObjectSnapshot(self._config['episode_id'],revision,source.key,objects,
            self._snapshot.aliases if aliases is None else aliases)

    def commit(self, source, batch, observations):
        with self._mutex:
            observations=tuple(observations)
            source_age=self._validate_source(source,batch,observations)
            key=canonical([source.key.episode_id,source.key.sensor_id,source.key.frame_index,
                self._config['detector_profile_id'],batch.vocabulary_id])
            payload_digest=_digest(dumps(source),dumps(batch),*(dumps(item) for item in observations))
            existing=self.ledger.batch(key)
            if existing is not None:
                if existing['payload_digest']!=payload_digest:
                    raise ValueError('conflicting repeated detector batch payload')
                return CommitResult(self._snapshot,())
            appearance_spec=self._appearance_spec_for(item.appearance for item in observations
                if item.appearance is not None)
            # Compute negatives against exactly the pre-commit geometry. Historical
            # or replay results never become current negative visibility evidence.
            current=(source_age<=750_000_000 and 'replay' not in source.clock_domain.lower()
                and source.capture_monotonic_ns>=self._capture_watermark)
            negatives=negative_visibility(source,batch,self._snapshot,current=current)
            trial=self._engine.fork()
            trial.advance_time(source.capture_monotonic_ns/1e9)
            adapted=tuple(AssociationObservation(source.key.episode_id,source.key.frame_index,
                item.detection_id,self._config['floor_id'],item.evidence_kind,
                item.category or item.raw_label,item.score,item.points_world,item.camera_position,
                source_geometry_sha256=item.geometry_hash,
                visual_embedding=None if item.appearance is None else item.appearance.vector) for item in observations)
            assigned=trial.ingest(adapted,now_s=source.capture_monotonic_ns/1e9)
            event_ids=tuple(_digest('object-evidence:v1',key,item.detection_id,item.evidence_kind) for item in observations)
            batch_id=_digest('detector-batch:v1',key)
            next_snapshot=self._build_snapshot(trial,source,observations,assigned.object_ids,event_ids,
                appearance_spec=appearance_spec)
            source_ref=self.assets.put(dumps(source).encode())
            batch_ref=self.assets.put(dumps(batch).encode())
            asset_refs={source_ref,batch_ref}
            views=[]
            ds={d.detection_id:d for d in batch.detections}
            common=dict(source=dict(episode_id=source.key.episode_id,sensor_id=source.key.sensor_id,
                frame_index=source.key.frame_index),capture_monotonic_ns=source.capture_monotonic_ns,
                clock_domain=source.clock_domain,geometry_hash=source.geometry_hash,
                calibration_id=source.calibration_id,pose_version=source.pose_version,
                detector_profile_id=self._config['detector_profile_id'],vocabulary_id=batch.vocabulary_id,
                temporal_status='current' if current else 'historical',source_asset=source_ref,
                batch_asset=batch_ref)
            # Store all masks/crops, including detections with unusable depth.
            detection_assets={}
            for detection in batch.detections:
                ys,xs=np.nonzero(detection.mask)
                crop=source.rgb[ys.min():ys.max()+1,xs.min():xs.max()+1]
                mask_ref=self.assets.put(_npy(detection.mask))
                crop_ref=self.assets.put(_npy(crop))
                asset_refs.update((mask_ref,crop_ref))
                detection_assets[detection.detection_id]=dict(mask_asset=mask_ref,crop_asset=crop_ref,
                    crop_bbox_xyxy=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)])
            for i,item in enumerate(observations):
                refs=detection_assets[item.detection_id]
                observation_ref=self.assets.put(dumps(item).encode())
                asset_refs.add(observation_ref)
                data=dict(common,detection_id=item.detection_id,evidence_kind=item.evidence_kind,
                    score=item.score,raw_label=item.raw_label,category=item.category,
                    camera_position=list(item.camera_position),object_revision=next_snapshot.revision,
                    crop_bbox_xyxy=refs['crop_bbox_xyxy'],observation_asset=observation_ref,
                    association_digest=trial._digest(adapted[i]))
                views.append((event_ids[i],assigned.object_ids[i],refs,data))
            record=dict(common,completion=batch.completion,cap_reached=batch.cap_reached,
                detections=detection_assets,projected_event_ids=list(event_ids))
            conn=self.ledger.connection
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.executemany('INSERT OR IGNORE INTO assets VALUES (?)',((ref,) for ref in sorted(asset_refs)))
                conn.execute('INSERT INTO batches VALUES (?,?,?,?,?,?)',
                    (key,payload_digest,batch_id,source_ref,batch_ref,canonical(record)))
                for event_id,object_id,refs,data in views:
                    conn.execute('INSERT INTO events VALUES (?,?,?,?)',(event_id,key,object_id,canonical(data)))
                    conn.execute('INSERT INTO views VALUES (?,?,?,?,?)',
                        (event_id,object_id,refs['mask_asset'],refs['crop_asset'],canonical(data)))
                appearance_ids=[]
                for i,item in enumerate(observations):
                    if item.appearance is not None:
                        attachment_id=_digest('appearance:v1',event_ids[i])
                        conn.execute('INSERT INTO appearances VALUES (?,?,?,?)',
                            (event_ids[i],assigned.object_ids[i],dumps(item.appearance),attachment_id))
                        appearance_ids.append(attachment_id)
                negative_ids=[]
                for negative in negatives:
                    negative_id=_digest('negative-visibility:v1',key,negative['object_id'])
                    data=dict(common,**negative)
                    conn.execute('INSERT INTO negatives VALUES (?,?,?,?)',
                        (negative_id,key,negative['object_id'],canonical(data)))
                    negative_ids.append(negative_id)
                watermark=max(self.dispatch_watermark,source.key.frame_index)
                capture_watermark=max(self._capture_watermark,source.capture_monotonic_ns)
                self._checkpoint(trial,next_snapshot,watermark,capture_watermark)
                if appearance_spec is not None:
                    self.ledger.set('appearance_spec',appearance_spec)
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK'); raise
            self._engine,self._snapshot=trial,next_snapshot
            self.dispatch_watermark,self._capture_watermark=watermark,capture_watermark
            return CommitResult(next_snapshot,(batch_id,)+event_ids+tuple(negative_ids)+tuple(appearance_ids))

    def merge(self, first_id, second_id):
        with self._mutex:
            first_id,second_id=self.resolve_id(first_id),self.resolve_id(second_id)
            trial=self._engine.fork()
            survivor=trial.merge_tracks(first_id,second_id)
            retired=second_id if survivor==first_id else first_id
            objects=dict(self._snapshot.objects)
            left,right=objects[survivor],objects.pop(retired)
            track=trial._tracks[survivor]; cloud=track.points_world
            lower,upper=cloud.min(axis=0),cloud.max(axis=0)
            revision=self._snapshot.revision+1
            appearance=self._aggregate_feature(track,self.ledger.get('appearance_spec'))
            objects[survivor]=replace(left,centroid=np.median(cloud,axis=0),bounds=np.stack((lower,upper)),
                points_world=cloud,footprint_xy=np.array([[lower[0],lower[1]],[upper[0],lower[1]],
                    [upper[0],upper[1]],[lower[0],upper[1]]]),
                lifecycle=track.status,evidence_refs=tuple(dict.fromkeys(left.evidence_refs+right.evidence_refs)),
                revision=revision,first_seen_ns=min(left.first_seen_ns,right.first_seen_ns),
                last_seen_ns=max(left.last_seen_ns,right.last_seen_ns),appearance=appearance,
                source=left.source if left.last_seen_ns>=right.last_seen_ns else right.source)
            aliases={k:survivor if v==retired else v for k,v in self._snapshot.aliases.items()}
            aliases[retired]=survivor
            snapshot=ObjectSnapshot(self._config['episode_id'],revision,self._snapshot.source,objects,aliases)
            conn=self.ledger.connection; conn.execute('BEGIN IMMEDIATE')
            try:
                for table in ('events','views','negatives','appearances'):
                    conn.execute(f'UPDATE {table} SET object_id=? WHERE object_id=?',(survivor,retired))
                self._checkpoint(trial,snapshot,self.dispatch_watermark,self._capture_watermark)
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK'); raise
            self._engine,self._snapshot=trial,snapshot
            return CommitResult(snapshot,(_digest('object-merge:v1',retired,survivor),))

    def attach_appearance(self, batch: AppearanceBatch):
        """Attach to accepted detected events only; feature never allocates identity."""
        with self._mutex:
            if not isinstance(batch,AppearanceBatch): raise ValueError('requires AppearanceBatch')
            appearance_spec=self._appearance_spec_for(batch.features.values())
            if batch.source.episode_id!=self._config['episode_id'] or batch.source.sensor_id!=self._config['primary_sensor_id']:
                raise ValueError('appearance source mismatch')
            key=canonical([batch.source.episode_id,batch.source.sensor_id,batch.source.frame_index,
                self._config['detector_profile_id'],self._config['vocabulary_id']])
            views={}
            for row in self.ledger.connection.execute(
                    'SELECT v.event_id,v.object_id,v.data FROM views v JOIN events e '
                    'ON v.event_id=e.event_id WHERE e.batch_key=?',(key,)):
                view=json.loads(row['data'])
                if view['evidence_kind']=='detected':
                    view.update(event_id=row['event_id'],object_id=row['object_id'])
                    views[view['detection_id']]=view
            objects=dict(self._snapshot.objects); changes=[]
            trial=self._engine.fork()
            for detection_id,feature in batch.features.items():
                view=views.get(detection_id)
                if view is None or view['geometry_hash']!=batch.geometry_hash:
                    raise ValueError('appearance requires committed detection source/geometry')
                event_id=view['event_id']; encoded=dumps(feature)
                existing=self.ledger.connection.execute('SELECT payload FROM appearances WHERE event_id=?',(event_id,)).fetchone()
                if existing is not None:
                    if existing[0]!=encoded: raise ValueError('conflicting appearance attachment')
                    continue
                object_id=view['object_id']
                if object_id is not None and object_id in trial._tracks:
                    obj=objects[object_id]
                    trial.attach_visual(object_id,feature.vector)
                    objects[obj.object_id]=replace(obj,appearance=self._aggregate_feature(
                        trial._tracks[object_id],appearance_spec),revision=self._snapshot.revision+1)
                changes.append((event_id,object_id,encoded,_digest('appearance:v1',event_id)))
            if not changes: return CommitResult(self._snapshot,())
            snapshot=replace(self._snapshot,revision=self._snapshot.revision+1,objects=objects)
            conn=self.ledger.connection; conn.execute('BEGIN IMMEDIATE')
            try:
                conn.executemany('INSERT INTO appearances VALUES (?,?,?,?)',changes)
                self._checkpoint(trial,snapshot,self.dispatch_watermark,self._capture_watermark)
                if appearance_spec is not None:
                    self.ledger.set('appearance_spec',appearance_spec)
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK'); raise
            self._engine,self._snapshot=trial,snapshot
            return CommitResult(snapshot,tuple(v[3] for v in changes))

    def close(self):
        with self._mutex: self.ledger.close()

    def __enter__(self): return self
    def __exit__(self,*exc): self.close()
