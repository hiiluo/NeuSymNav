"""Atomic source journal and bounded worker lifecycle helpers.

The journal contains only schema-v1 RGB-D source bytes and result contracts.
Recovery streams SQL rows; no all-event Python manifest is retained.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from threading import Thread
import time
from ..contracts import Observation
from ..contracts.serialization import dumps,loads


def atomic_write(path,data):
    temp=path.with_name(path.name+'.tmp')
    with temp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


class Journal:
    """A connection must be constructed/used/closed in its worker thread."""
    def __init__(self,root,config):
        self.root=Path(root);self.raw=self.root/'keyframes';self.raw.mkdir(parents=True,exist_ok=True)
        self.conn=sqlite3.connect(self.root/'runtime.sqlite',timeout=5,isolation_level=None)
        self.conn.execute('PRAGMA journal_mode=WAL');self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS config (value TEXT NOT NULL)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS frames (idx INTEGER PRIMARY KEY, payload TEXT NOT NULL, sha TEXT NOT NULL, size INTEGER NOT NULL, state TEXT NOT NULL, result TEXT, prepared TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
        encoded=json.dumps(config,sort_keys=True)
        row=self.conn.execute('SELECT value FROM config').fetchone()
        if row and row[0]!=encoded:self.conn.close();raise ValueError('runtime journal episode/profile/clock mismatch')
        if not row:self.conn.execute('INSERT INTO config VALUES (?)',(encoded,))

    def accept(self,obs):
        data=dumps(obs).encode();name=f'frame-{obs.key.frame_index:012d}.json';path=self.raw/name
        digest=hashlib.sha256(data).hexdigest()
        existing=self.conn.execute('SELECT sha FROM frames WHERE idx=?',(obs.key.frame_index,)).fetchone()
        if existing:
            if existing[0]!=digest:raise ValueError('conflicting source identity')
            return name
        if path.exists() and path.read_bytes()!=data:raise ValueError('conflicting orphan source asset')
        atomic_write(path,data)
        # Durable source exists before the admission transaction can become ACK.
        self.conn.execute('INSERT INTO frames VALUES (?,?,?,?,?,NULL,NULL)',(obs.key.frame_index,name,digest,len(data),'accepted'))
        return name

    def load(self,index):
        row=self.conn.execute('SELECT payload,sha,size FROM frames WHERE idx=?',(index,)).fetchone()
        if row is None:raise ValueError('missing accepted source')
        name,sha,size=row
        if name!=f'frame-{index:012d}.json' or size>32*1024**2:raise ValueError('invalid source reference')
        path=self.raw/name
        if path.is_symlink() or path.stat().st_size!=size:raise ValueError('source size/reference mismatch')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('accepted source checksum mismatch')
        obs=loads(data.decode())
        if not isinstance(obs,Observation) or obs.key.frame_index!=index:raise ValueError('source identity mismatch')
        return obs

    def watermark(self,index=None):
        if index is not None:
            self.conn.execute("INSERT INTO meta VALUES ('dispatch_watermark',?) ON CONFLICT(key) DO UPDATE SET value=max(value,excluded.value)",(index,))
        row=self.conn.execute("SELECT value FROM meta WHERE key='dispatch_watermark'").fetchone()
        return -1 if row is None else row[0]

    def next_pending(self):
        row=self.conn.execute("SELECT idx FROM frames WHERE state!='done' ORDER BY idx LIMIT 1").fetchone()
        return None if row is None else row[0]

    def result(self,index,batch=None):
        if batch is not None:self.conn.execute('UPDATE frames SET result=? WHERE idx=?',(dumps(batch),index))
        row=self.conn.execute('SELECT result FROM frames WHERE idx=?',(index,)).fetchone()
        return None if row is None or row[0] is None else loads(row[0])

    def prepared(self,index,items=None):
        if items is not None:
            payload=json.dumps([dumps(item) for item in items],separators=(',',':'))
            self.conn.execute('UPDATE frames SET prepared=? WHERE idx=?',(payload,index))
        row=self.conn.execute('SELECT prepared FROM frames WHERE idx=?',(index,)).fetchone()
        return None if row is None or row[0] is None else tuple(loads(item) for item in json.loads(row[0]))

    def done(self,index):self.conn.execute("UPDATE frames SET state='done' WHERE idx=?",(index,))
    def counts(self):
        total=self.conn.execute('SELECT count(*) FROM frames').fetchone()[0]
        done=self.conn.execute("SELECT count(*) FROM frames WHERE state='done'").fetchone()[0]
        return dict(accepted=total,committed=done,pending=total-done)
    def close(self):self.conn.close()


def valid_timeout(timeout_s):
    if isinstance(timeout_s,bool) or not isinstance(timeout_s,(int,float)) or not math.isfinite(timeout_s) or timeout_s<0:
        raise ValueError('timeout_s must be finite and nonnegative')
    return float(timeout_s)


def background(name,fn):
    thread=Thread(target=fn,name='neusymnav-'+name,daemon=True);thread.start();return thread


def remaining(deadline):return max(0.,deadline-time.monotonic())
