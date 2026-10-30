"""Qt-free, revision-checked display publication and command acknowledgement seam.

The publisher retains one immutable envelope. A consumer reads that single
reference, so map, objects, hierarchy and evidence cannot be mixed across
separate reads. Image arrays are copied into owned read-only buffers before
publication. No renderer, model, simulator or graph owner is imported here.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping
from math import isfinite
from threading import RLock
from time import monotonic_ns
from types import MappingProxyType
from typing import Literal
from uuid import UUID, uuid4

import numpy as np

from ..contracts import FrameKey, HierarchySnapshot, NavSnapshot, ObjectSnapshot, age_ns


from .robot_overlay import RobotTrack
from .navigation_overlay import NavigationOverlay


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ENVELOPE_IMAGE_BYTES = 32 * 1024 * 1024
MAX_BEST_VIEWS = 3
MAX_VERIFICATION_RECORDS = 4096
MAX_VERIFICATION_EVIDENCE = 32
_METRIC_KEYS = frozenset({
    "captured_frame_id", "processed_frame_id", "published_frame_id",
    "source_age_ns", "dropped_count", "replaced_count", "actual_profile",
    "sources",
})


def _frame_key(value: object, name: str, episode_id: str | None = None) -> FrameKey | None:
    if value is None:
        return None
    if not isinstance(value, FrameKey):
        raise ValueError(f"{name} must be FrameKey or None")
    if episode_id is not None and value.episode_id != episode_id:
        raise ValueError(f"{name} belongs to a different episode")
    return value


def _owned_rgb(value: object) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] != 3:
        raise ValueError("display image must be a uint8 HxWx3 RGB ndarray")
    if value.shape[0] == 0 or value.shape[1] == 0 or value.nbytes > MAX_IMAGE_BYTES:
        raise ValueError("display image is empty or exceeds the per-image byte cap")
    owned = np.frombuffer(np.ascontiguousarray(value).tobytes(order="C"), dtype=np.uint8)
    return owned.reshape(value.shape)


@dataclass(frozen=True, slots=True)
class DisplayImage:
    """Owned pixels with explicit capture or graph-evidence provenance."""

    purpose: Literal["rgb", "best_view"]
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    pixels: np.ndarray
    object_id: str | None = None
    object_revision: int | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.purpose not in {"rgb", "best_view"}:
            raise ValueError("unsupported display image purpose")
        if not isinstance(self.source, FrameKey):
            raise ValueError("display image requires a FrameKey source")
        if type(self.capture_monotonic_ns) is not int or self.capture_monotonic_ns < 0:
            raise ValueError("capture_monotonic_ns must be a nonnegative integer")
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain must be nonempty")
        object.__setattr__(self, "pixels", _owned_rgb(self.pixels))
        if self.purpose == "rgb":
            if any(value is not None for value in (self.object_id, self.object_revision, self.evidence_ref)):
                raise ValueError("RGB frame cannot claim object evidence provenance")
        else:
            if not isinstance(self.object_id, str) or not self.object_id.strip():
                raise ValueError("best view requires an object ID")
            if type(self.object_revision) is not int or self.object_revision < 0:
                raise ValueError("best view requires a nonnegative object revision")
            if not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip():
                raise ValueError("best view requires a source evidence reference")


@dataclass(frozen=True, slots=True)
class DisplayInstance:
    """One detector output in source-image coordinates; not a canonical ID."""

    detection_id: str
    label: str
    score: float
    mask: np.ndarray

    def __post_init__(self):
        if not isinstance(self.detection_id, str) or not 0 < len(self.detection_id) <= 256:
            raise ValueError('bounded detection ID required')
        if not isinstance(self.label, str) or not 0 < len(self.label) <= 256:
            raise ValueError('bounded detection label required')
        if type(self.score) not in (int, float) or not isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError('finite detector confidence in [0,1] required')
        mask = self.mask
        if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.ndim != 2 or not mask.size or mask.nbytes > MAX_IMAGE_BYTES:
            raise ValueError('bounded HxW bool detector mask required')
        object.__setattr__(self, 'mask', np.frombuffer(mask.tobytes(), dtype=np.bool_).reshape(mask.shape))


@dataclass(frozen=True, slots=True)
class DisplayObservation:
    """A bounded detector observation with its OWN exact original RGB frame."""

    image: DisplayImage
    instances: tuple[DisplayInstance, ...]
    total_detections: int
    completion: str
    cap_reached: bool

    def __post_init__(self):
        if not isinstance(self.image, DisplayImage) or self.image.purpose != 'rgb':
            raise ValueError('detector observation requires its RGB source image')
        items = tuple(self.instances)
        if len(items) > 64 or any(not isinstance(item, DisplayInstance) for item in items):
            raise ValueError('at most 64 typed display instances required')
        if type(self.total_detections) is not int or self.total_detections < len(items):
            raise ValueError('total detections must include all displayed instances')
        if self.completion not in {'complete', 'partial', 'failed', 'unknown'} or type(self.cap_reached) is not bool:
            raise ValueError('explicit detector completion and cap status required')
        if any(item.mask.shape != self.image.pixels.shape[:2] for item in items):
            raise ValueError('mask shape must match its exact observation image')
        if sum(item.mask.nbytes for item in items) > MAX_IMAGE_BYTES:
            raise ValueError('detector mask aggregate byte cap exceeded')
        object.__setattr__(self, 'instances', items)

    @property
    def payload_bytes(self):
        return self.image.pixels.nbytes + sum(item.mask.nbytes for item in self.instances)


@dataclass(frozen=True, slots=True)
class DisplayVerificationEvidence:
    """Small provenance tag for one verifier source event; carries no asset bytes."""

    source: FrameKey
    object_revision: int
    capture_monotonic_ns: int
    clock_domain: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, FrameKey):
            raise ValueError("verification evidence requires a FrameKey source")
        for name in ("object_revision", "capture_monotonic_ns"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("verification evidence requires a clock domain")
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip():
            raise ValueError("verification evidence requires an evidence reference")


@dataclass(frozen=True, slots=True)
class DisplayVerificationRecord:
    """Verifier result for one canonical object at its exact object revision."""

    episode_id: str
    object_id: str
    object_revision: int
    status: Literal["verified", "unverified", "unknown"]
    evidence: tuple[DisplayVerificationEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.episode_id, str) or not self.episode_id.strip():
            raise ValueError("verification record episode_id must be nonempty")
        if not isinstance(self.object_id, str) or not self.object_id.strip():
            raise ValueError("verification record object_id must be nonempty")
        if type(self.object_revision) is not int or self.object_revision < 0:
            raise ValueError("verification record object_revision must be nonnegative")
        if self.status not in {"verified", "unverified", "unknown"}:
            raise ValueError("verification status must be verified, unverified, or unknown")
        evidence = tuple(self.evidence)
        if len(evidence) > MAX_VERIFICATION_EVIDENCE or any(
            not isinstance(item, DisplayVerificationEvidence) for item in evidence
        ):
            raise ValueError(f"verification evidence must contain at most {MAX_VERIFICATION_EVIDENCE} typed tags")
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True, slots=True)
class DisplayVerificationSnapshot:
    """Optional lightweight verifier publication pinned to an object snapshot revision."""

    episode_id: str
    object_revision: int
    objects: Mapping[str, DisplayVerificationRecord]

    def __post_init__(self) -> None:
        if not isinstance(self.episode_id, str) or not self.episode_id.strip():
            raise ValueError("verification snapshot episode_id must be nonempty")
        if type(self.object_revision) is not int or self.object_revision < 0:
            raise ValueError("verification snapshot object_revision must be nonnegative")
        if not isinstance(self.objects, Mapping) or len(self.objects) > MAX_VERIFICATION_RECORDS:
            raise ValueError("verification objects must be a bounded mapping")
        records: dict[str, DisplayVerificationRecord] = {}
        for object_id, record in self.objects.items():
            if not isinstance(object_id, str) or not object_id.strip():
                raise ValueError("verification object keys must be canonical IDs")
            if not isinstance(record, DisplayVerificationRecord) or record.object_id != object_id:
                raise ValueError("verification mapping keys must match typed canonical records")
            if record.episode_id != self.episode_id:
                raise ValueError("verification record belongs to a different episode")
            records[object_id] = record
        object.__setattr__(self, "objects", MappingProxyType(records))


@dataclass(frozen=True, slots=True)
class DisplaySources:
    """Optional source data, each pinned or individually tagged for display."""

    nav: NavSnapshot | None = None
    objects: ObjectSnapshot | None = None
    verification: DisplayVerificationSnapshot | None = None
    rgb: DisplayImage | None = None
    best_views: tuple[DisplayImage, ...] = ()
    robot: RobotTrack | None = None
    observation: DisplayObservation | None = None
    navigation: NavigationOverlay | None = None

    def __post_init__(self) -> None:
        if self.nav is not None and not isinstance(self.nav, NavSnapshot):
            raise ValueError("nav source must be NavSnapshot or None")
        if self.objects is not None and not isinstance(self.objects, ObjectSnapshot):
            raise ValueError("objects source must be ObjectSnapshot or None")
        if self.verification is not None and not isinstance(self.verification, DisplayVerificationSnapshot):
            raise ValueError("verification source must be DisplayVerificationSnapshot or None")
        if self.rgb is not None and (not isinstance(self.rgb, DisplayImage) or self.rgb.purpose != "rgb"):
            raise ValueError("rgb source must be an RGB DisplayImage or None")
        if self.observation is not None and not isinstance(self.observation, DisplayObservation):
            raise ValueError('typed detector observation required')
        if self.robot is not None and not isinstance(self.robot, RobotTrack):
            raise ValueError('typed robot display trail required')
        if self.navigation is not None and not isinstance(self.navigation,NavigationOverlay):
            raise ValueError('typed navigation display required')
        views = tuple(self.best_views)
        if len(views) > MAX_BEST_VIEWS or any(
            not isinstance(view, DisplayImage) or view.purpose != "best_view" for view in views
        ):
            raise ValueError(f"best_views must contain at most {MAX_BEST_VIEWS} best-view images")
        object.__setattr__(self, "best_views", views)


@dataclass(frozen=True, slots=True)
class DisplayMetrics:
    captured_frame_id: FrameKey | None
    processed_frame_id: FrameKey | None
    published_frame_id: FrameKey | None
    source_age_ns: Mapping[str, int | None]
    dropped_count: int
    replaced_count: int
    actual_profile: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_frame_id", _frame_key(self.captured_frame_id, "captured_frame_id"))
        object.__setattr__(self, "processed_frame_id", _frame_key(self.processed_frame_id, "processed_frame_id"))
        object.__setattr__(self, "published_frame_id", _frame_key(self.published_frame_id, "published_frame_id"))
        if type(self.dropped_count) is not int or self.dropped_count < 0:
            raise ValueError("dropped_count must be a nonnegative integer")
        if type(self.replaced_count) is not int or self.replaced_count < 0:
            raise ValueError("replaced_count must be a nonnegative integer")
        if self.actual_profile is not None and (not isinstance(self.actual_profile, str) or not self.actual_profile.strip()):
            raise ValueError("actual_profile must be a nonempty string or None")
        if not isinstance(self.source_age_ns, Mapping) or len(self.source_age_ns) > 64:
            raise ValueError("source_age_ns must be a mapping with at most 64 entries")
        ages: dict[str, int | None] = {}
        for name, age in self.source_age_ns.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("source age names must be nonempty strings")
            if age is not None and (type(age) is not int or age < 0):
                raise ValueError(f"source age for {name!r} must be nonnegative or None")
            ages[name] = age
        object.__setattr__(self, "source_age_ns", MappingProxyType(ages))


@dataclass(frozen=True, slots=True)
class DisplayEnvelope:
    """One complete publication and the independent age of that publication."""

    publication_sequence: int
    hierarchy: HierarchySnapshot
    metrics: DisplayMetrics
    sources: DisplaySources
    published_monotonic_ns: int
    clock_domain: str

    def __post_init__(self) -> None:
        if type(self.publication_sequence) is not int or self.publication_sequence < 1:
            raise ValueError("publication_sequence must be positive")
        if not isinstance(self.hierarchy, HierarchySnapshot):
            raise ValueError("hierarchy must be HierarchySnapshot")
        if not isinstance(self.metrics, DisplayMetrics) or not isinstance(self.sources, DisplaySources):
            raise ValueError("typed display metrics and sources are required")
        if type(self.published_monotonic_ns) is not int or self.published_monotonic_ns < 0:
            raise ValueError("published_monotonic_ns must be nonnegative")
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain must be nonempty")
        # Keep the envelope closed even when constructed outside the publisher.
        DisplayPublisher._validate_episode(self.hierarchy, self.metrics)
        DisplayPublisher._validate_sources(self.hierarchy, self.metrics, self.sources)
        if self.sources.navigation is not None and self.sources.navigation.clock_domain!=self.clock_domain:
            raise ValueError('planner display clock mismatch')
        image_bytes = sum(
            image.pixels.nbytes for image in ((self.sources.rgb,) if self.sources.rgb is not None else ()) + self.sources.best_views
        )
        if self.sources.observation is not None:
            image_bytes += self.sources.observation.payload_bytes
            if self.sources.observation.image.clock_domain != self.clock_domain:
                raise ValueError('detector observation clock mismatch')
        if image_bytes > MAX_ENVELOPE_IMAGE_BYTES:
            raise ValueError("display image payload exceeds the envelope byte cap")

    def publication_age_ns(self, now_ns: int, clock_domain: str) -> int:
        """Return output age separately from every source age."""
        return age_ns(self.published_monotonic_ns, self.clock_domain, now_ns, clock_domain)


class DisplayPublisher:
    """Atomically replace and read the latest revision-coherent display value."""

    def __init__(self, *, clock_domain: str, now_ns: Callable[[], int] = monotonic_ns) -> None:
        if not isinstance(clock_domain, str) or not clock_domain.strip():
            raise ValueError("clock_domain must be nonempty")
        if not callable(now_ns):
            raise ValueError("now_ns must be callable")
        self._clock_domain = clock_domain
        self._now_ns = now_ns
        self._lock = RLock()
        self._latest: DisplayEnvelope | None = None
        self._sequence = 0

    def publish(self, snapshot: HierarchySnapshot, metrics: Mapping[str, object]) -> None:
        """Validate one closed source bundle, then atomically publish it."""
        if not isinstance(snapshot, HierarchySnapshot):
            raise ValueError("snapshot must be HierarchySnapshot")
        if not isinstance(metrics, Mapping) or set(metrics) != _METRIC_KEYS:
            missing = sorted(_METRIC_KEYS - set(metrics)) if isinstance(metrics, Mapping) else sorted(_METRIC_KEYS)
            extra = sorted((repr(key) for key in set(metrics) - _METRIC_KEYS)) if isinstance(metrics, Mapping) else []
            raise ValueError(f"metrics keys must match the closed display schema; missing={missing}, extra={extra}")
        sources = metrics["sources"]
        if not isinstance(sources, DisplaySources):
            raise ValueError("metrics['sources'] must be DisplaySources")
        telemetry = DisplayMetrics(
            metrics["captured_frame_id"], metrics["processed_frame_id"], metrics["published_frame_id"],
            metrics["source_age_ns"], metrics["dropped_count"], metrics["replaced_count"], metrics["actual_profile"],
        )
        self._validate_sources(snapshot, telemetry, sources)
        self._validate_episode(snapshot, telemetry)

        with self._lock:
            previous = self._latest
            if previous is not None:
                old = previous.hierarchy
                if snapshot.revision < old.revision:
                    raise ValueError("hierarchy revision moved backward")
                if snapshot.revision == old.revision and (
                    snapshot.object_revision, snapshot.map_revision, snapshot.region_revision,
                    snapshot.latest_nav_revision,
                ) != (old.object_revision, old.map_revision, old.region_revision, old.latest_nav_revision):
                    raise ValueError("one hierarchy revision cannot refer to different source revisions")
            total_image_bytes = sum(
                image.pixels.nbytes for image in ((sources.rgb,) if sources.rgb is not None else ()) + sources.best_views
            )
            if sources.observation is not None:
                total_image_bytes += sources.observation.payload_bytes
            if total_image_bytes > MAX_ENVELOPE_IMAGE_BYTES:
                raise ValueError("display image payload exceeds the envelope byte cap")
            self._sequence += 1
            self._latest = DisplayEnvelope(
                self._sequence, snapshot, telemetry, sources, self._now_ns(), self._clock_domain,
            )

    def read_latest(self) -> DisplayEnvelope | None:
        """Return one immutable pointer snapshot; this method never assembles data."""
        with self._lock:
            return self._latest

    @staticmethod
    def _validate_episode(snapshot: HierarchySnapshot, metrics: DisplayMetrics) -> None:
        for name in ("captured_frame_id", "processed_frame_id", "published_frame_id"):
            key = getattr(metrics, name)
            if key is not None and key.episode_id != snapshot.episode_id:
                raise ValueError(f"{name} belongs to a different episode")

    @staticmethod
    def _validate_sources(snapshot: HierarchySnapshot, metrics: DisplayMetrics, sources: DisplaySources) -> None:
        if sources.navigation is not None:
            plan=sources.navigation
            if plan.source.episode_id!=snapshot.episode_id or (sources.nav is not None and plan.clock_domain!=sources.nav.clock_domain):
                raise ValueError('planner display episode/clock mismatch')
        if sources.observation is not None:
            if sources.observation.image.source.episode_id != snapshot.episode_id:
                raise ValueError('detector observation belongs to a different episode')
        if sources.nav is not None:
            if sources.nav.episode_id != snapshot.episode_id or sources.nav.revision != snapshot.map_revision:
                raise ValueError("display NavSnapshot must match the hierarchy's pinned episode/map revision")
        if sources.robot is not None:
            nav = sources.nav
            sample = sources.robot.samples[-1]
            if nav is None or (sample.source, sample.capture_monotonic_ns, sample.clock_domain) != (nav.source, nav.capture_monotonic_ns, nav.clock_domain):
                raise ValueError('robot display trail must match pinned map source/time/clock')
        if sources.objects is not None:
            if sources.objects.episode_id != snapshot.episode_id or sources.objects.revision != snapshot.object_revision:
                raise ValueError("display ObjectSnapshot must match the hierarchy's pinned episode/object revision")
        if sources.verification is not None:
            verification = sources.verification
            if verification.episode_id != snapshot.episode_id:
                raise ValueError("verification source belongs to a different episode")
            if sources.objects is None:
                raise ValueError("verification source requires the pinned ObjectSnapshot")
            if not verification.objects.keys() <= sources.objects.objects.keys():
                raise ValueError("verification records must use canonical IDs from the pinned ObjectSnapshot")
            for record in verification.objects.values():
                for evidence in record.evidence:
                    if evidence.source.episode_id != snapshot.episode_id:
                        raise ValueError("verification evidence belongs to a different episode")
                    if evidence.object_revision > record.object_revision:
                        raise ValueError("verification evidence cannot come from a future object revision")
            if "verification" not in metrics.source_age_ns:
                raise ValueError("verification source requires an explicit verification source age")
        if sources.rgb is not None:
            if sources.rgb.source.episode_id != snapshot.episode_id:
                raise ValueError("RGB image source belongs to a different episode")
            if "rgb" not in metrics.source_age_ns:
                raise ValueError("RGB source requires an explicit rgb source age")
        if sources.nav is not None and "map" not in metrics.source_age_ns:
            raise ValueError("map source requires an explicit map source age")
        if sources.objects is not None and "objects" not in metrics.source_age_ns:
            raise ValueError("object source requires an explicit objects source age")
        if sources.best_views and sources.objects is None:
            raise ValueError("best views require the pinned ObjectSnapshot used to validate them")
        for view in sources.best_views:
            if view.source.episode_id != snapshot.episode_id:
                raise ValueError("best-view source belongs to a different episode")
            if view.object_revision != snapshot.object_revision or view.object_revision != sources.objects.revision:
                raise ValueError("best view object revision does not match the pinned hierarchy/object snapshot")
            try:
                object_id = sources.objects.resolve_id(view.object_id)
            except KeyError as exc:
                raise ValueError("best view references an unknown canonical object or alias") from exc
            if view.evidence_ref not in sources.objects.objects[object_id].evidence_refs:
                raise ValueError("best-view evidence reference is absent from the pinned object history")


@dataclass(frozen=True, slots=True)
class UiCommand:
    request_uuid: str
    action: Literal["pause", "stop"]
    source: str
    requested_monotonic_ns: int
    clock_domain: str

    def __post_init__(self) -> None:
        try:
            UUID(self.request_uuid)
        except (ValueError, AttributeError) as exc:
            raise ValueError("request_uuid must be a UUID") from exc
        if self.action not in {"pause", "stop"}:
            raise ValueError("UI command action must be pause or stop")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("command source must be nonempty")
        if type(self.requested_monotonic_ns) is not int or self.requested_monotonic_ns < 0:
            raise ValueError("requested_monotonic_ns must be nonnegative")
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("command clock_domain must be nonempty")


@dataclass(frozen=True, slots=True)
class UiCommandAck:
    request_uuid: str
    status: Literal["accepted", "rejected"]
    reason: str | None
    handled_monotonic_ns: int
    clock_domain: str

    def __post_init__(self) -> None:
        try:
            UUID(self.request_uuid)
        except (ValueError, AttributeError) as exc:
            raise ValueError("ACK request_uuid must be a UUID") from exc
        if self.status not in {"accepted", "rejected"}:
            raise ValueError("ACK status must be accepted or rejected")
        if self.status == "rejected" and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("rejected ACK requires a reason")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ValueError("ACK reason must be a string or None")
        if type(self.handled_monotonic_ns) is not int or self.handled_monotonic_ns < 0:
            raise ValueError("handled_monotonic_ns must be nonnegative")
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("ACK clock_domain must be nonempty")


@dataclass(frozen=True, slots=True)
class UiCommandStatus:
    request_uuid: str
    action: Literal["pause", "stop"]
    state: Literal["pending", "acknowledged", "rejected", "timed_out", "submission_failed"]
    reason: str | None
    requested_monotonic_ns: int
    clock_domain: str


class UiControlClient:
    """Injectable pause/stop seam; only an explicit matching ACK means success."""

    def __init__(
        self,
        *,
        command_source: str,
        submit: Callable[[UiCommand], UiCommandAck | None],
        clock_domain: str,
        ack_timeout_s: float = 2.0,
        now_ns: Callable[[], int] = monotonic_ns,
    ) -> None:
        if not isinstance(command_source, str) or not command_source.strip():
            raise ValueError("command_source must be nonempty")
        if not callable(submit) or not callable(now_ns):
            raise ValueError("submit and now_ns must be callable")
        if not isinstance(clock_domain, str) or not clock_domain.strip():
            raise ValueError("clock_domain must be nonempty")
        if (isinstance(ack_timeout_s, bool) or not isinstance(ack_timeout_s, (int, float))
                or not isfinite(ack_timeout_s) or ack_timeout_s <= 0):
            raise ValueError("ack_timeout_s must be positive")
        self._source = command_source
        self._submit = submit
        self._clock_domain = clock_domain
        self._timeout_ns = int(ack_timeout_s * 1_000_000_000)
        self._now_ns = now_ns
        self._lock = RLock()
        self._statuses: dict[str, UiCommandStatus] = {}
        self._order: list[str] = []

    def request(self, action: str) -> UiCommandStatus:
        if not isinstance(action, str) or action not in {"pause", "stop"}:
            raise ValueError("UI control supports pause and stop only")
        now = self._now_ns()
        command = UiCommand(str(uuid4()), action, self._source, now, self._clock_domain)
        status = UiCommandStatus(command.request_uuid, action, "pending", None, now, self._clock_domain)
        with self._lock:
            for request_uuid, prior in tuple(self._statuses.items()):
                if prior.state == "pending" and now - prior.requested_monotonic_ns >= self._timeout_ns:
                    self._statuses[request_uuid] = UiCommandStatus(
                        prior.request_uuid, prior.action, "timed_out",
                        f"No ACK received within {self._timeout_ns / 1_000_000_000:g} seconds",
                        prior.requested_monotonic_ns, prior.clock_domain,
                    )
            if sum(prior.state == "pending" for prior in self._statuses.values()) >= 8:
                raise RuntimeError("too many unacknowledged UI commands")
            self._statuses[command.request_uuid] = status
            self._order.append(command.request_uuid)
            self._trim_history()
        try:
            ack = self._submit(command)
        except Exception as exc:
            status = UiCommandStatus(command.request_uuid, action, "submission_failed", str(exc), now, self._clock_domain)
            with self._lock:
                self._statuses[command.request_uuid] = status
            return status
        if ack is not None:
            try:
                self.accept_ack(ack)
            except ValueError as exc:
                status = UiCommandStatus(command.request_uuid, action, "submission_failed", str(exc), now, self._clock_domain)
                with self._lock:
                    self._statuses[command.request_uuid] = status
                return status
        return self.status(command.request_uuid)

    def accept_ack(self, ack: UiCommandAck) -> UiCommandStatus:
        if not isinstance(ack, UiCommandAck):
            raise ValueError("ACK must be UiCommandAck")
        with self._lock:
            prior = self._statuses.get(ack.request_uuid)
            if prior is None:
                raise ValueError("ACK does not match a known UI request")
            if prior.state != "pending":
                raise ValueError(f"ACK arrived after request state became {prior.state}")
            if ack.clock_domain != prior.clock_domain:
                raise ValueError("ACK clock domain differs from its request")
            if ack.handled_monotonic_ns < prior.requested_monotonic_ns:
                raise ValueError("ACK predates its request")
            now = self._now_ns()
            elapsed = age_ns(prior.requested_monotonic_ns, prior.clock_domain, now, self._clock_domain)
            if ack.handled_monotonic_ns > now:
                raise ValueError("ACK handling time is in the future")
            if elapsed >= self._timeout_ns:
                timed_out = UiCommandStatus(
                    prior.request_uuid, prior.action, "timed_out",
                    f"No ACK received within {self._timeout_ns / 1_000_000_000:g} seconds",
                    prior.requested_monotonic_ns, prior.clock_domain,
                )
                self._statuses[prior.request_uuid] = timed_out
                return timed_out
            state = "acknowledged" if ack.status == "accepted" else "rejected"
            status = UiCommandStatus(prior.request_uuid, prior.action, state, ack.reason, prior.requested_monotonic_ns, prior.clock_domain)
            self._statuses[prior.request_uuid] = status
            return status

    def status(self, request_uuid: str) -> UiCommandStatus:
        with self._lock:
            try:
                current = self._statuses[request_uuid]
            except KeyError as exc:
                raise KeyError(request_uuid) from exc
            if current.state == "pending":
                elapsed = age_ns(current.requested_monotonic_ns, current.clock_domain, self._now_ns(), self._clock_domain)
                if elapsed >= self._timeout_ns:
                    current = UiCommandStatus(
                        current.request_uuid, current.action, "timed_out",
                        f"No ACK received within {self._timeout_ns / 1_000_000_000:g} seconds",
                        current.requested_monotonic_ns, current.clock_domain,
                    )
                    self._statuses[request_uuid] = current
            return current

    def latest_statuses(self) -> tuple[UiCommandStatus, ...]:
        with self._lock:
            keys = tuple(self._order[-8:])
            return tuple(self.status(key) for key in keys)

    def _trim_history(self) -> None:
        while len(self._order) > 64:
            terminal_index = next((index for index, request_uuid in enumerate(self._order)
                                   if self._statuses[request_uuid].state != "pending"), None)
            if terminal_index is None:
                break
            expired = self._order.pop(terminal_index)
            self._statuses.pop(expired, None)


__all__ = [
    "DisplayInstance", "DisplayObservation", "DisplayEnvelope", "DisplayImage", "DisplayMetrics", "DisplayPublisher", "DisplaySources",
    "DisplayVerificationEvidence", "DisplayVerificationRecord", "DisplayVerificationSnapshot",
    "UiCommand", "UiCommandAck", "UiCommandStatus", "UiControlClient",
]
