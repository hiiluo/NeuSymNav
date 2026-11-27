"""Lifecycle fallback for a native build without event-level continuity proof."""
from dataclasses import replace

from ..contracts.reasoninggraph import GraphLifecycleDelta, GraphReadToken


def _graph_scope(native):
    return (native.episode_id, native.run_id, native.world_epoch,
            native.source_sha256, native.build_sha256, native.config_sha256)


def validate_progress(before, after):
    old, new = before.native, after.native
    scope = lambda token: (_graph_scope(token.native), token.source.sensor_id, token.clock_domain,
                           token.calibration_id, token.calibration_hash, token.vocabulary_id,
                           token.labelspace_hash, token.detector_profile_id)
    if scope(after) != scope(before):
        raise ValueError('lifecycle scope changed; reopen the adapter')
    if new.graph_revision < old.graph_revision:
        raise ValueError('cannot rebase to an older graph')
    if new.graph_revision == old.graph_revision:
        if replace(after, sidecar_revision=before.sidecar_revision) != before:
            raise ValueError('conflicting source identity for native revision')
        if after.sidecar_revision < before.sidecar_revision:
            raise ValueError('cannot restore an older sidecar revision')
    elif (after.source.frame_index <= before.source.frame_index
          or after.capture_monotonic_ns <= before.capture_monotonic_ns):
        raise ValueError('new graph requires a later accepted source')


def apply_delta(previous, native_snapshot, native_lineage=None):
    if not isinstance(native_snapshot, GraphReadToken) or (
            previous is not None and not isinstance(previous, GraphReadToken)):
        raise TypeError('lifecycle replacement requires exact graph tokens')
    if native_lineage is not None:
        raise ValueError('native lifecycle proof is unavailable for this adapter')
    if previous is not None:
        validate_progress(previous, native_snapshot)
    rebase = previous is None or previous.native != native_snapshot.native
    return GraphLifecycleDelta(previous, native_snapshot, requires_rebase=rebase)
