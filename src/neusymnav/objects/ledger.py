"""Schema-v1 SQLite WAL object ledger and committed evidence query boundary.

Every owner operation writes its trial state and event rows in one transaction.
Assets are immutable and fsynced first. A crash may leave unreferenced assets;
accepted references are never published before COMMIT.
"""
from __future__ import annotations
import fcntl
import json
from pathlib import Path
import sqlite3


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Ledger:
    def __init__(self, root, config):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = (self.root / 'owner.lock').open('a+b')
        self.connection = None
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lock.close()
            raise RuntimeError('object ledger already has an owner') from exc
        try:
            self.connection = sqlite3.connect(self.root / 'objects.sqlite3', isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA journal_mode=WAL')
            self.connection.execute('PRAGMA synchronous=FULL')
            self.connection.execute('PRAGMA foreign_keys=ON')
            version = self.connection.execute('PRAGMA user_version').fetchone()[0]
            tables = self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in (0, 1) or (version == 0 and tables):
                raise ValueError('unsupported ledger schema; explicit migration required')
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assets(ref TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS batches(
                    batch_key TEXT PRIMARY KEY, payload_digest TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE, source_asset TEXT NOT NULL REFERENCES assets(ref),
                    batch_asset TEXT NOT NULL REFERENCES assets(ref), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    event_id TEXT PRIMARY KEY, batch_key TEXT NOT NULL REFERENCES batches(batch_key),
                    object_id TEXT, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS views(
                    event_id TEXT PRIMARY KEY REFERENCES events(event_id), object_id TEXT,
                    mask_asset TEXT NOT NULL REFERENCES assets(ref),
                    crop_asset TEXT NOT NULL REFERENCES assets(ref), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS negatives(
                    event_id TEXT PRIMARY KEY, batch_key TEXT NOT NULL REFERENCES batches(batch_key),
                    object_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS appearances(
                    event_id TEXT PRIMARY KEY REFERENCES events(event_id), object_id TEXT,
                    payload TEXT NOT NULL, attachment_id TEXT UNIQUE NOT NULL);
                PRAGMA user_version=1;
            ''')
            prior = self.get('config')
            encoded = canonical(config)
            if prior is not None and prior != encoded:
                raise ValueError('ledger episode/profile/vocabulary/clock configuration mismatch')
            if prior is None:
                self.connection.execute('INSERT INTO metadata VALUES (?,?)', ('config', encoded))
            if self.connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('ledger integrity check failed')
            if self.connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('ledger dangling evidence reference')
        except BaseException:
            self.close()
            raise

    def get(self, key):
        row = self.connection.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return None if row is None else row[0]

    def set(self, key, value):
        self.connection.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def batch(self, key):
        row = self.connection.execute('SELECT * FROM batches WHERE batch_key=?', (key,)).fetchone()
        return None if row is None else dict(row)

    def batch_records(self):
        records=[]
        for row in self.connection.execute('SELECT * FROM batches ORDER BY rowid'):
            value=json.loads(row['data'])
            value.update({k: row[k] for k in ('batch_key','event_id','source_asset','batch_asset','payload_digest')})
            records.append(value)
        return tuple(records)

    def committed_views(self, event_ids=None):
        """Only committed detection evidence; source/camera/depth/mask/crop refs.

        ``event_ids`` may be CommitResult IDs. Batch IDs have no view. Object ID
        is the current canonical endpoint after merges; original source stays.
        """
        ids=None if event_ids is None else set(event_ids)
        result=[]
        for row in self.connection.execute('SELECT * FROM views ORDER BY rowid'):
            if ids is None or row['event_id'] in ids:
                value=json.loads(row['data'])
                value.update(event_id=row['event_id'], object_id=row['object_id'],
                    mask_asset=row['mask_asset'], crop_asset=row['crop_asset'])
                result.append(value)
        return tuple(result)

    def negative_records(self, event_ids=None):
        ids=None if event_ids is None else set(event_ids)
        result=[]
        for row in self.connection.execute('SELECT * FROM negatives ORDER BY rowid'):
            if ids is None or row['event_id'] in ids:
                value=json.loads(row['data'])
                value.update(event_id=row['event_id'], object_id=row['object_id'])
                result.append(value)
        return tuple(result)

    def appearance_records(self):
        return tuple(dict(row) for row in self.connection.execute(
            'SELECT * FROM appearances ORDER BY rowid'))

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection=None
        if not self._lock.closed:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
            self._lock.close()
