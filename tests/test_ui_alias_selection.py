"""A merge or removal can arrive while an actual dashboard retains selection."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from PyQt5 import QtWidgets
import pytest
from neusymnav.contracts import ObjectSnapshot
from neusymnav.hierarchy import HierarchyComposer
from neusymnav.visualization.desktop import DashboardWindow
from neusymnav.visualization.publisher import DisplaySources
from test_display_snapshot import make_publisher,OID,ALIAS,CANDIDATE
from test_membership import regions


@pytest.fixture
def app():return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_selected_old_canonical_resolves_after_alias_merge_refresh(app):
    publisher,hierarchy,metrics,objects,nav,now=make_publisher(with_images=False)
    old=replace(objects.objects[OID],object_id=ALIAS)
    before=ObjectSnapshot(objects.episode_id,objects.revision,objects.source,{ALIAS:old},{})
    before_h=HierarchyComposer().compose(before,nav,regions(),latest_nav_revision=2,now_ns=200,clock_domain='clock')
    publisher.publish(before_h,{**metrics,'sources':DisplaySources(objects=before,nav=nav)})
    window=DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:200);window.show();app.processEvents()
    try:
        assert window.select_object(ALIAS)==ALIAS
        publisher.publish(hierarchy,metrics)
        window.refresh();app.processEvents()
        assert window._selected_object_id==OID
        assert f'Object {OID}' in window.object_details.text()
        assert 'Selected alias resolves' in window.object_details.text()
        assert 'Verification source events: 2' in window.object_details.text()
        assert 'camA:0 (clock)' in window.object_details.text()
    finally:window.close();app.processEvents()


def test_removed_selection_without_alias_is_unavailable_not_retargeted(app):
    publisher,hierarchy,metrics,objects,nav,now=make_publisher(with_images=False)
    window=DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:200);window.show();app.processEvents()
    try:
        window.select_object(OID)
        remaining=ObjectSnapshot(objects.episode_id,objects.revision+1,objects.source,{CANDIDATE:objects.objects[CANDIDATE]}, {})
        after_h=HierarchyComposer().compose(remaining,nav,regions(),latest_nav_revision=2,now_ns=200,clock_domain='clock')
        publisher.publish(replace(after_h,revision=hierarchy.revision+1),{**metrics,'sources':DisplaySources(objects=remaining,nav=nav)})
        window.refresh();app.processEvents()
        assert window._selected_object_id==OID
        assert 'Selection unavailable' in window.object_details.text()
        assert 'selected object unavailable' in window.best_view_caption.text()
        with pytest.raises(KeyError):window.select_object(OID)
    finally:window.close();app.processEvents()
