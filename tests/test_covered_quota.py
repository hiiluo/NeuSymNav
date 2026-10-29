"""A bounded archive reservation replaces only its explicitly owned subtree."""
import os
from pathlib import Path

import pytest

from neusymnav.runtime.quota import QuotaExceeded, RunQuota


def archive(tmp_path):
    path = tmp_path / 'keyframes' / 'recording'
    path.mkdir(parents=True)
    return path


def test_covered_archive_is_pruned_and_full_bound_stays_charged(tmp_path, monkeypatch):
    covered = archive(tmp_path)
    for index in range(200):
        (covered / str(index)).write_bytes(b'x')
    (tmp_path / 'keyframes' / 'other').write_bytes(b'x' * 10)
    (tmp_path / 'store.sqlite-wal').write_bytes(b'x' * 20)
    quota = RunQuota(tmp_path, raw_cap=1010, total_cap=1050)
    quota.reserve('archive', 1000, 1000, covered_path=covered)
    real_scandir = os.scandir

    def checked_scandir(path):
        assert not Path(path).is_relative_to(covered), 'enumerated covered payloads'
        return real_scandir(path)

    monkeypatch.setattr(os, 'scandir', checked_scandir)
    quota.reserve('navigation', 20)
    assert quota.snapshot()['peak_total'] == 1050
    assert quota.snapshot()['peak_raw'] == 1010
    with pytest.raises(QuotaExceeded):
        quota.reserve('extra', 1)
    with pytest.raises(QuotaExceeded):
        quota.reserve('raw-extra', 1, 1)
    assert quota.snapshot()['reserved_total'] == 1020


def test_release_restores_actual_subtree_accounting(tmp_path):
    covered = archive(tmp_path)
    (covered / 'frame').write_bytes(b'x' * 40)
    quota = RunQuota(tmp_path, raw_cap=100, total_cap=100)
    quota.reserve('archive', 100, 100, covered_path=covered)
    quota.release('archive')
    quota.reserve('new', 60, 60)
    with pytest.raises(QuotaExceeded):
        quota.reserve('one-too-many', 1)


def test_initial_existing_payload_must_fit_bound(tmp_path):
    covered = archive(tmp_path)
    (covered / 'frame').write_bytes(b'x' * 101)
    quota = RunQuota(tmp_path, raw_cap=200, total_cap=200)
    with pytest.raises(QuotaExceeded):
        quota.reserve('archive', 100, 100, covered_path=covered)
    assert quota.snapshot()['reserved_total'] == 0
    # No failed cover may hide already accepted evidence.
    with pytest.raises(QuotaExceeded):
        quota.reserve('other', 100)


@pytest.mark.parametrize('total,raw', [(100, 0), (100, 99), (100, 101), (0, 0), (-1, -1)])
def test_raw_cover_requires_full_positive_raw_charge(tmp_path, total, raw):
    covered = archive(tmp_path)
    quota = RunQuota(tmp_path)
    with pytest.raises(ValueError):
        quota.reserve('archive', total, raw, covered_path=covered)


def test_nonraw_cover_and_raw_ancestor_are_not_confused(tmp_path):
    covered = tmp_path / 'assets'
    covered.mkdir()
    quota = RunQuota(tmp_path)
    with pytest.raises(ValueError):
        quota.reserve('assets', 100, 100, covered_path=covered)
    quota.reserve('assets', 100, covered_path=covered)
    with pytest.raises(ValueError):
        quota.reserve('run', 100, covered_path=tmp_path)


def test_existing_cover_cannot_be_removed_moved_or_resized_by_reserve(tmp_path):
    covered = archive(tmp_path)
    other = tmp_path / 'keyframes' / 'other'
    other.mkdir()
    quota = RunQuota(tmp_path)
    quota.reserve('archive', 100, 100, covered_path=covered)
    quota.reserve('archive', 100, 100, covered_path=covered)
    for kwargs in ({}, {'covered_path': other}, {'covered_path': covered}):
        with pytest.raises(ValueError):
            quota.reserve('archive', 101, 101, **kwargs)
    with pytest.raises(ValueError):
        quota.reserve('archive', 100, 100)


def test_covers_cannot_overlap_or_repurpose_an_existing_reservation(tmp_path):
    covered = archive(tmp_path)
    nested = covered / 'nested'
    nested.mkdir()
    quota = RunQuota(tmp_path)
    quota.reserve('archive', 100, 100, covered_path=covered)
    for candidate in (nested, covered, covered.parent):
        with pytest.raises(ValueError):
            quota.reserve('collision', 100, 100, covered_path=candidate)
    quota.reserve('ordinary', 10)
    with pytest.raises(ValueError):
        quota.reserve('ordinary', 100, 100, covered_path=covered.parent / 'new')


def test_cover_rejects_escape_missing_file_and_symlinks(tmp_path):
    covered = archive(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    (covered / 'file').write_bytes(b'x')
    (tmp_path / 'link').symlink_to(covered, target_is_directory=True)
    quota = RunQuota(tmp_path)
    for candidate in (outside, covered / 'missing', covered / 'file', tmp_path / 'link'):
        with pytest.raises(ValueError):
            quota.reserve('archive', 100, 100, covered_path=candidate)
    (covered / 'evil').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        quota.reserve('archive', 100, 100, covered_path=covered)


def test_cover_rejects_symlink_ancestor(tmp_path):
    covered = archive(tmp_path)
    (tmp_path / 'shortcut').symlink_to(covered.parent, target_is_directory=True)
    quota = RunQuota(tmp_path)
    with pytest.raises(ValueError):
        quota.reserve('archive', 100, covered_path=tmp_path / 'shortcut' / 'recording')


def test_uncovered_scan_errors_fail_closed(tmp_path, monkeypatch):
    covered = archive(tmp_path)
    quota = RunQuota(tmp_path)
    quota.reserve('archive', 100, 100, covered_path=covered)
    inaccessible = tmp_path / 'unreserved'
    inaccessible.mkdir()
    real_scandir = os.scandir

    def denied(path):
        if Path(path) == inaccessible:
            raise PermissionError('cannot scan unreserved evidence')
        return real_scandir(path)

    monkeypatch.setattr(os, 'scandir', denied)
    with pytest.raises(PermissionError):
        quota.reserve('new', 1)
    assert quota.snapshot()['reserved_total'] == 100


def test_replaced_cover_and_uncovered_symlink_fail_closed(tmp_path):
    covered = archive(tmp_path)
    quota = RunQuota(tmp_path)
    quota.reserve('archive', 100, 100, covered_path=covered)
    covered.rename(covered.with_name('old'))
    covered.mkdir()
    with pytest.raises(ValueError):
        quota.reserve('other', 10)
    covered.rmdir()
    covered.with_name('old').rename(covered)
    (tmp_path / 'elsewhere').symlink_to(covered, target_is_directory=True)
    with pytest.raises(ValueError):
        quota.reserve('other', 10)


def test_ordinary_reservations_keep_conservative_legacy_accounting(tmp_path):
    covered = archive(tmp_path)
    (covered / 'frame').write_bytes(b'x' * 40)
    quota = RunQuota(tmp_path, raw_cap=100, total_cap=100)
    quota.reserve('archive', 60, 60)
    assert quota.snapshot()['peak_total'] == 100
    with pytest.raises(QuotaExceeded):
        quota.reserve('other', 1)
