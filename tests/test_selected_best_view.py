"""Lazy selected-object images are not limited by the global three-image preview."""
from dataclasses import replace
import hashlib
import io
import json
import sqlite3
import numpy as np
from test_display_snapshot import make_publisher, VERIFIED
from neusymnav.runtime.ui_transport import encode_publication, decode_publication


def fixture(tmp_path):
    envelope=make_publisher(with_images=False)[0].read_latest()
    objects=envelope.sources.objects;obj=objects.objects[VERIFIED]
    obj=replace(obj,evidence_refs=('event-3',)+tuple(f'later-{i}' for i in range(40)))
    objects=replace(objects,objects={**objects.objects,VERIFIED:obj})
    envelope=replace(envelope,sources=replace(envelope.sources,objects=objects))
    root=tmp_path/'assets';root.mkdir()
    buffer=io.BytesIO();np.save(buffer,np.full((8,9,3),42,np.uint8),allow_pickle=False)
    payload=buffer.getvalue();ref=hashlib.sha256(payload).hexdigest();(root/ref).write_bytes(payload)
    proof=envelope.sources.verification.objects[VERIFIED].evidence[0]
    data=dict(evidence_kind='detected',object_revision=proof.object_revision,source=dict(episode_id=proof.source.episode_id,
        sensor_id=proof.source.sensor_id,frame_index=proof.source.frame_index),
        capture_monotonic_ns=proof.capture_monotonic_ns,clock_domain=proof.clock_domain)
    with sqlite3.connect(tmp_path/'objects.sqlite3') as c:
        c.execute('CREATE TABLE views(event_id TEXT,object_id TEXT,crop_asset TEXT,data TEXT)')
        c.execute('INSERT INTO views VALUES(?,?,?,?)',(proof.evidence_ref,VERIFIED,ref,json.dumps(data)))
    return envelope,root,ref


def test_lazy_selected_object_loads_image_missing_from_previews(tmp_path):
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    envelope,root,_=fixture(tmp_path)
    reader=SelectedBestViewReader(root,clock_domain=envelope.clock_domain)
    view=reader.read(envelope,VERIFIED)
    assert view.object_id==VERIFIED and view.evidence_ref=='event-3'
    assert np.all(view.pixels==42) and view.object_revision==envelope.sources.objects.revision
    assert reader.read(envelope,VERIFIED) is view  # only one image cached


def test_transport_preserves_selected_gallery_proof_older_than_last32(tmp_path):
    envelope,_,_=fixture(tmp_path)
    decoded=decode_publication(encode_publication(envelope))
    assert 'event-3' in decoded.sources.objects.objects[VERIFIED].evidence_refs


def test_corrupt_asset_and_wrong_episode_never_get_displayed(tmp_path):
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    envelope,root,ref=fixture(tmp_path)
    (root/ref).write_bytes(b'corrupt')
    assert SelectedBestViewReader(root,clock_domain=envelope.clock_domain).read(envelope,VERIFIED) is None
    assert SelectedBestViewReader(root,clock_domain='foreign').read(envelope,VERIFIED) is None


def test_alias_selection_and_metadata_mismatch(tmp_path):
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    from test_membership import ALIAS
    envelope,root,_=fixture(tmp_path)
    objects=replace(envelope.sources.objects,aliases={ALIAS:VERIFIED})
    envelope=replace(envelope,sources=replace(envelope.sources,objects=objects))
    assert SelectedBestViewReader(root,clock_domain=envelope.clock_domain).read(envelope,ALIAS).object_id==VERIFIED
    with sqlite3.connect(tmp_path/'objects.sqlite3') as c:
        row=json.loads(c.execute('select data from views').fetchone()[0])
        row['source']['episode_id']='foreign'
        c.execute('update views set data=?',(json.dumps(row),))
    assert SelectedBestViewReader(root,clock_domain=envelope.clock_domain).read(envelope,VERIFIED) is None


def test_unreadable_top_gallery_view_falls_back_to_next_committed_view(tmp_path):
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    envelope,root,ref=fixture(tmp_path)
    record=envelope.sources.verification.objects[VERIFIED];first=record.evidence[0]
    second=replace(first,evidence_ref='fallback')
    verification=replace(envelope.sources.verification,objects={VERIFIED:replace(record,evidence=(first,second))})
    obj=envelope.sources.objects.objects[VERIFIED]
    objects=replace(envelope.sources.objects,objects={**envelope.sources.objects.objects,
        VERIFIED:replace(obj,evidence_refs=obj.evidence_refs+('fallback',))})
    envelope=replace(envelope,sources=replace(envelope.sources,objects=objects,verification=verification))
    with sqlite3.connect(tmp_path/'objects.sqlite3') as c:
        data=c.execute('select data from views').fetchone()[0]
        c.execute('update views set crop_asset=?',('0'*64,))
        c.execute('insert into views values(?,?,?,?)',('fallback',VERIFIED,ref,data))
    image=SelectedBestViewReader(root,clock_domain=envelope.clock_domain).read(envelope,VERIFIED)
    assert image.evidence_ref=='fallback'


def test_oversized_npy_header_is_rejected_before_array_allocation(tmp_path):
    import pytest
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    _,root,_=fixture(tmp_path);buffer=io.BytesIO()
    np.lib.format.write_array_header_1_0(buffer,dict(descr='|u1',fortran_order=False,shape=(2**32,2**32,3)))
    payload=buffer.getvalue();ref=hashlib.sha256(payload).hexdigest();(root/ref).write_bytes(payload)
    with pytest.raises(ValueError,match='bounded RGB'):
        SelectedBestViewReader(root,clock_domain='clock')._pixels(ref)


def test_real_dashboard_selection_loads_crop_and_clears_for_missing_object(tmp_path):
    import pytest
    QtWidgets=pytest.importorskip('PyQt5.QtWidgets')
    from neusymnav.visualization.desktop import DashboardWindow
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    from test_display_snapshot import CANDIDATE
    envelope,root,_=fixture(tmp_path)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    reader=SelectedBestViewReader(root,clock_domain=envelope.clock_domain)
    window=DashboardWindow(lambda:envelope,clock_domain=envelope.clock_domain,
        now_ns=lambda:200,best_view_provider=reader.read)
    try:
        window.select_object(VERIFIED)
        assert window.best_view.pixmap() is not None and not window.best_view.pixmap().isNull()
        assert 'event-3' in window.best_view_caption.text()
        window.select_object(CANDIDATE)
        assert window.best_view.pixmap() is None or window.best_view.pixmap().isNull()
    finally:window.close();app.processEvents()


def test_persisted_evidence_revision_must_match_pinned_proof(tmp_path):
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    envelope,root,_=fixture(tmp_path)
    with sqlite3.connect(tmp_path/'objects.sqlite3') as c:
        data=json.loads(c.execute('select data from views').fetchone()[0])
        data['object_revision']+=1
        c.execute('update views set data=?',(json.dumps(data),))
    assert SelectedBestViewReader(root,clock_domain=envelope.clock_domain).read(envelope,VERIFIED) is None
