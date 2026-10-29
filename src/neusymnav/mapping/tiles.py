"""Checksummed, compressed persistence for evicted occupancy tiles."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Mapping

import numpy as np


class TileArchiveError(RuntimeError):
    """Raised when an archived tile cannot be safely read or written."""


class TileArchive:
    """Store dense occupancy tiles as atomically replaced compressed NPZ files.

    Each archive includes its key, schema version, array shapes and dtypes, and
    a SHA-256 digest over all metadata and array bytes. Reads validate every
    field before returning arrays to the mapper.
    """

    FORMAT_VERSION = 1
    _ARRAY_NAMES = ("planar_log_odds", "height_log_odds", "floor_support")

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        if directory is None:
            self._temporary_directory = tempfile.TemporaryDirectory(prefix="occupancy-tiles-")
            self.directory = Path(self._temporary_directory.name)
        else:
            self.directory = Path(directory)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TileArchiveError(f"tile archive directory unavailable: {exc}") from exc
        existing_keys = self._scan_keys()
        if directory is not None and existing_keys:
            raise TileArchiveError(
                "tile archive directory already contains tiles; reset or choose an empty directory"
            )
        self._known_keys = set(existing_keys)

    def path_for(self, key: tuple[int, int]) -> Path:
        row, col = self._validated_key(key)
        return self.directory / f"tile_{row}_{col}.npz"

    @property
    def tile_keys(self) -> tuple[tuple[int, int], ...]:
        return tuple(sorted(self._known_keys))

    def _scan_keys(self) -> tuple[tuple[int, int], ...]:
        keys = []
        for path in self.directory.glob("tile_*_*.npz"):
            stem = path.stem
            parts = stem.split("_")
            if len(parts) != 3 or parts[0] != "tile":
                raise TileArchiveError(f"unrecognized tile archive filename: {path.name}")
            try:
                keys.append((int(parts[1]), int(parts[2])))
            except ValueError as exc:
                raise TileArchiveError(f"unrecognized tile archive filename: {path.name}") from exc
        return tuple(sorted(set(keys)))

    @property
    def disk_bytes(self) -> int:
        total = 0
        for key in self.tile_keys:
            try:
                total += self.path_for(key).stat().st_size
            except FileNotFoundError:
                continue
        return total

    def contains(self, key: tuple[int, int]) -> bool:
        normalized_key = self._validated_key(key)
        path = self.path_for(normalized_key)
        try:
            path.stat()
        except FileNotFoundError:
            if normalized_key in self._known_keys:
                raise TileArchiveError(f"tile archive file is missing for {normalized_key}")
            return False
        except OSError as exc:
            raise TileArchiveError(f"tile archive lookup failed for {normalized_key}: {exc}") from exc
        self._known_keys.add(normalized_key)
        return True

    def write_many(
        self,
        tiles: Mapping[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]],
    ) -> None:
        """Stage compressed tiles before atomically replacing each destination.

        If staging any file fails, existing archive files are untouched. A rare
        destination replacement failure can leave earlier destinations updated;
        those files still contain exact copies of unchanged resident tiles, and
        the mapper evicts nothing unless the whole call succeeds.
        """
        staged: list[tuple[tuple[int, int], Path, Path]] = []
        try:
            for key, values in tiles.items():
                arrays = self._validate_arrays(values)
                digest = self._digest(key, arrays)
                destination = self.path_for(key)
                temporary_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w+b", prefix=f".{destination.name}.", suffix=".tmp", dir=self.directory,
                        delete=False,
                    ) as temporary:
                        temporary_path = Path(temporary.name)
                        np.savez_compressed(
                            temporary,
                            format_version=np.asarray(self.FORMAT_VERSION, dtype=np.int64),
                            key=np.asarray(key, dtype=np.int64),
                            planar_log_odds=arrays[0],
                            height_log_odds=arrays[1],
                            floor_support=arrays[2],
                            sha256=np.asarray(digest),
                        )
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    staged.append((self._validated_key(key), temporary_path, destination))
                    temporary_path = None
                finally:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
            for key, temporary_path, destination in staged:
                os.replace(temporary_path, destination)
                self._known_keys.add(key)
        except TileArchiveError:
            raise
        except Exception as exc:
            raise TileArchiveError(f"tile archive write failed: {exc}") from exc
        finally:
            for _, temporary_path, _ in staged:
                temporary_path.unlink(missing_ok=True)

    def read(
        self,
        key: tuple[int, int],
        *,
        tile_size_cells: int,
        height_bin_count: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Read and validate one tile, returning independent writable arrays."""
        key = self._validated_key(key)
        path = self.path_for(key)
        try:
            with np.load(path, allow_pickle=False) as payload:
                expected_fields = {
                    "format_version", "key", *self._ARRAY_NAMES, "sha256"
                }
                if set(payload.files) != expected_fields:
                    raise TileArchiveError("tile archive schema validation failed")
                format_version = payload["format_version"]
                archived_key = payload["key"]
                if format_version.shape != () or int(format_version) != self.FORMAT_VERSION:
                    raise TileArchiveError("tile archive schema version is unsupported")
                if format_version.dtype != np.dtype(np.int64):
                    raise TileArchiveError("tile archive schema version dtype is invalid")
                if (
                    archived_key.shape != (2,)
                    or archived_key.dtype != np.dtype(np.int64)
                    or not np.array_equal(archived_key, key)
                ):
                    raise TileArchiveError("tile archive key validation failed")
                arrays = tuple(np.array(payload[name], copy=True, order="C") for name in self._ARRAY_NAMES)
                expected_shapes = (
                    (tile_size_cells, tile_size_cells),
                    (tile_size_cells, tile_size_cells, height_bin_count),
                    (tile_size_cells, tile_size_cells),
                )
                expected_dtypes = (np.dtype(np.float32), np.dtype(np.float32), np.dtype(np.bool_))
                for array, expected_shape, expected_dtype in zip(arrays, expected_shapes, expected_dtypes):
                    if array.shape != expected_shape or array.dtype != expected_dtype:
                        raise TileArchiveError("tile archive shape or dtype validation failed")
                if any(
                    np.isinf(array).any() or np.any(array[~np.isnan(array)] < -4.0)
                    or np.any(array[~np.isnan(array)] > 4.0)
                    for array in arrays[:2]
                ):
                    raise TileArchiveError("tile archive log-odds values are invalid")
                stored_digest = payload["sha256"]
                if stored_digest.shape != () or stored_digest.dtype.kind not in "US":
                    raise TileArchiveError("tile archive checksum field is invalid")
                actual_digest = self._digest(key, arrays)
                if str(stored_digest.item()) != actual_digest:
                    raise TileArchiveError("tile archive checksum mismatch")
                return arrays  # type: ignore[return-value]
        except TileArchiveError:
            raise
        except Exception as exc:
            raise TileArchiveError(f"tile archive read failed for {key}: {exc}") from exc

    def clear(self) -> None:
        """Remove archived tiles; failure leaves mapper memory untouched."""
        try:
            for key in self.tile_keys:
                self.path_for(key).unlink(missing_ok=True)
                self._known_keys.discard(key)
        except OSError as exc:
            raise TileArchiveError(f"tile archive clear failed: {exc}") from exc

    @classmethod
    def _digest(
        cls,
        key: tuple[int, int],
        arrays: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> str:
        digest = hashlib.sha256()
        digest.update(b"occupancy-tile-archive-v1\0")
        digest.update(np.asarray(key, dtype="<i8").tobytes())
        for name, array in zip(cls._ARRAY_NAMES, arrays):
            contiguous = np.ascontiguousarray(array)
            digest.update(name.encode("ascii") + b"\0")
            digest.update(contiguous.dtype.str.encode("ascii") + b"\0")
            digest.update(np.asarray(contiguous.shape, dtype="<i8").tobytes())
            digest.update(contiguous.tobytes())
        return digest.hexdigest()

    @staticmethod
    def _validated_key(key: tuple[int, int]) -> tuple[int, int]:
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) for value in key)
        ):
            raise ValueError("tile key must be an integer (row, col) pair")
        return int(key[0]), int(key[1])

    @staticmethod
    def _validate_arrays(
        values: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if len(values) != 3:
            raise TileArchiveError("tile archive arrays are incomplete")
        arrays = tuple(np.ascontiguousarray(value) for value in values)
        if arrays[0].dtype != np.dtype(np.float32):
            raise TileArchiveError("planar tile dtype is invalid")
        if arrays[1].dtype != np.dtype(np.float32):
            raise TileArchiveError("height tile dtype is invalid")
        if arrays[2].dtype != np.dtype(np.bool_):
            raise TileArchiveError("floor-support tile dtype is invalid")
        if arrays[0].shape != arrays[1].shape[:2] or arrays[0].shape != arrays[2].shape:
            raise TileArchiveError("tile array shapes are inconsistent")
        return arrays  # type: ignore[return-value]
