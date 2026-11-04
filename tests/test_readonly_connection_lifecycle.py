"""Actual display readers release SQLite handles even if GC is delayed."""
import json
import sqlite3
from types import SimpleNamespace

import pytest


def track_connections(monkeypatch):
    original = sqlite3.connect
    captured = []
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        captured.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', connect)
    return captured


@pytest.mark.parametrize('reader', ['best_view', 'detector', 'cloud', 'transport'])
def test_reader_closes_connection_after_read(tmp_path, monkeypatch, reader):
    from test_selected_best_view import fixture, VERIFIED
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    from neusymnav.visualization.detector_observation import CommittedObservationReader
    from neusymnav.visualization.point_cloud import CommittedCloudReader
    from neusymnav.runtime.ui_transport import UiProcess

    if reader in ('best_view', 'transport'):
        envelope, assets, _ = fixture(tmp_path)
        if reader == 'best_view':
            call = lambda: SelectedBestViewReader(assets, clock_domain=envelope.clock_domain).read(envelope, VERIFIED)
        else:
            ui = UiProcess.__new__(UiProcess)
            ui.assets_root = assets
            call = lambda: ui._images(envelope.sources)
    else:
        assets = tmp_path/'assets'; assets.mkdir()
        with sqlite3.connect(tmp_path/'objects.sqlite3') as db:
            db.execute('CREATE TABLE batches(source_asset TEXT,batch_asset TEXT,data TEXT)')
            db.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
            db.execute('INSERT INTO metadata VALUES (?,?)', ('config', json.dumps({'episode_id':'e','clock_domain':'c'})))
        if reader == 'detector':
            call = lambda: CommittedObservationReader(assets,clock_domain='c').read(object())
        else:
            envelope = SimpleNamespace(hierarchy=SimpleNamespace(episode_id='e'),clock_domain='c')
            call = lambda: CommittedCloudReader(assets).read(envelope)
    connections = track_connections(monkeypatch)
    call()
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')


def test_reader_close_allows_last_writer_to_remove_wal(tmp_path, monkeypatch):
    from neusymnav.visualization.detector_observation import CommittedObservationReader
    assets = tmp_path/'assets'; assets.mkdir()
    db_path = tmp_path/'objects.sqlite3'
    writer = sqlite3.connect(db_path)
    try:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        writer.execute('CREATE TABLE batches(source_asset TEXT,batch_asset TEXT)')
        writer.commit()
        wal = tmp_path/'objects.sqlite3-wal'
        assert wal.exists() and wal.stat().st_size > 0
        connections = track_connections(monkeypatch)
        assert CommittedObservationReader(assets,clock_domain='c').read(object()) is None
        writer.close()
        assert not wal.exists()
        assert len(connections) == 1
    finally:
        writer.close()
        for connection in locals().get('connections', []): connection.close()


@pytest.mark.parametrize('reader', ['detector', 'cloud'])
def test_reader_closes_connection_after_database_error(tmp_path, monkeypatch, reader):
    from neusymnav.visualization.detector_observation import CommittedObservationReader
    from neusymnav.visualization.point_cloud import CommittedCloudReader
    assets = tmp_path/'assets'; assets.mkdir()
    sqlite3.connect(tmp_path/'objects.sqlite3').close()
    connections = track_connections(monkeypatch)
    if reader == 'detector':
        call = lambda: CommittedObservationReader(assets,clock_domain='c').read(object())
    else:
        envelope = SimpleNamespace(hierarchy=SimpleNamespace(episode_id='e'),clock_domain='c')
        call = lambda: CommittedCloudReader(assets).read(envelope)
    with pytest.raises(sqlite3.OperationalError):
        call()
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')


def test_export_closes_connection_when_later_query_fails(tmp_path, monkeypatch):
    from neusymnav.runtime.launcher import _export
    objects = tmp_path/'objects'; objects.mkdir()
    connection = sqlite3.connect(objects/'objects.sqlite3')
    connection.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
    connection.close()
    pipeline = SimpleNamespace(snapshot_bundle=lambda: (None, None))
    connections = track_connections(monkeypatch)
    with pytest.raises(sqlite3.OperationalError, match='events'):
        _export(tmp_path, pipeline, {'clean_shutdown': True}, {'outcome':'completed'})
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')
