#!/usr/bin/env python3
"""Build a private timing-only Hydra DSO from the locked RoomFinder source."""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
TOOL_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = ROOT / "runs/hydra-objectnav/B1-stability-validation-20261107/benchmark-harness"
LOCK_PATH = ARTIFACT_DIR / "input-lock.json"
BASE_SOURCE = TOOL_DIR / "room_finder_base.cpp"
STABLE_SOURCE = ROOT / "tools/native/hydra_room_stability/room_finder.cpp"
STABLE_DSO = ROOT / "runs/hydra-objectnav/B1-stability-20261107/native/libhydra.so"
BUILD_DIR = ROOT / ".runtime/hydra_ws/build/hydra"
FLAGS_PATH = BUILD_DIR / "CMakeFiles/hydra.dir/flags.make"
LINK_PATH = BUILD_DIR / "CMakeFiles/hydra.dir/link.txt"
EXPECTED_TIMED_BASE_SHA256 = "1c0a7ac828a5681f7d32c77865b91c3c10168764160931f714147fded0f734fd"
EXPECTED_STABLE_DSO_SHA256 = "9364ca487e8826112705d942ff01734cdbe3372fbdcc91c21c42a14a42fb7e4b"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def instrument_source(source: str) -> str:
    source = replace_once(
        source,
        "#include <nlohmann/json.hpp>\n",
        "#include <nlohmann/json.hpp>\n#include <atomic>\n#include <chrono>\n",
        "timing headers",
    )
    source = replace_once(
        source,
        'Json decision = {{"enabled", false}, {"action", "not_called"}};\n',
        '''Json decision = {{"enabled", false}, {"action", "not_called"}};
struct TimingCounters {
  std::atomic<uint64_t> calls{0};
  std::atomic<uint64_t> nanoseconds{0};
};
TimingCounters get_best_components_timing;
TimingCounters find_rooms_timing;
class TimingScope {
 public:
  explicit TimingScope(TimingCounters& counters)
      : counters_(counters), started_(std::chrono::steady_clock::now()) {}
  ~TimingScope() noexcept {
    const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - started_).count();
    counters_.nanoseconds.fetch_add(static_cast<uint64_t>(elapsed), std::memory_order_relaxed);
    counters_.calls.fetch_add(1, std::memory_order_relaxed);
  }

 private:
  TimingCounters& counters_;
  std::chrono::steady_clock::time_point started_;
};
''',
        "counter and RAII declarations",
    )
    source = replace_once(
        source,
        "}\nextern \"C\" const char* nsn_room_stability_version()",
        '''}
extern "C" void nsn_hydra_room_timing_reset() {
  get_best_components_timing.calls.store(0, std::memory_order_relaxed);
  get_best_components_timing.nanoseconds.store(0, std::memory_order_relaxed);
  find_rooms_timing.calls.store(0, std::memory_order_relaxed);
  find_rooms_timing.nanoseconds.store(0, std::memory_order_relaxed);
}
extern "C" const char* nsn_hydra_room_timing_read() {
  thread_local std::string result;
  result = Json{{"schema_version", 1},
                {"getBestComponents", {{"calls", get_best_components_timing.calls.load(std::memory_order_relaxed)},
                                       {"nanoseconds", get_best_components_timing.nanoseconds.load(std::memory_order_relaxed)}}},
                {"findRooms", {{"calls", find_rooms_timing.calls.load(std::memory_order_relaxed)},
                               {"nanoseconds", find_rooms_timing.nanoseconds.load(std::memory_order_relaxed)}}}}.dump();
  return result.c_str();
}
extern "C" const char* nsn_room_stability_version()''',
        "timing C ABI",
    )
    source = replace_once(
        source,
        "InitialClusters RoomFinder::getBestComponents(const SceneGraphLayer& places) const {\n",
        "InitialClusters RoomFinder::getBestComponents(const SceneGraphLayer& places) const {\n  TimingScope timing(get_best_components_timing);\n",
        "getBestComponents RAII scope",
    )
    source = replace_once(
        source,
        "SceneGraphLayer::Ptr RoomFinder::findRooms(const SceneGraphLayer& places) {\n",
        "SceneGraphLayer::Ptr RoomFinder::findRooms(const SceneGraphLayer& places) {\n  TimingScope timing(find_rooms_timing);\n",
        "findRooms RAII scope",
    )
    return source


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    def require_locked(name: str, path: Path) -> str:
        resolved = path.resolve(strict=True)
        actual = sha256(resolved)
        expected = lock["inputs"][name]["sha256"]
        if actual != expected:
            raise RuntimeError(f"locked input changed: {name}: {actual} != {expected}")
        return actual

    base_sha = require_locked("stable_room_finder_source", STABLE_SOURCE)
    require_locked("stable_private_dso", STABLE_DSO)
    require_locked("hydra_flags_make", FLAGS_PATH)
    require_locked("hydra_link_txt", LINK_PATH)
    if base_sha != EXPECTED_TIMED_BASE_SHA256 or sha256(BASE_SOURCE) != base_sha:
        raise RuntimeError("benchmark base TU is not byte-identical to the locked final source")
    if sha256(STABLE_DSO) != EXPECTED_STABLE_DSO_SHA256:
        raise RuntimeError("stable reference DSO no longer has the locked SHA")

    out = ARTIFACT_DIR / "native"
    out.mkdir(parents=True, exist_ok=True)
    stable_resolved = STABLE_DSO.resolve(strict=True)
    dso_path = out / "libhydra.so"
    if dso_path.resolve() == stable_resolved:
        raise RuntimeError("refusing to overwrite the stable reference DSO")
    source_text = BASE_SOURCE.read_text(encoding="utf-8")
    timed_text = instrument_source(source_text)
    generated_source = out / "room_finder_timed.cpp"
    generated_source.write_text(timed_text, encoding="utf-8")
    diff = difflib.unified_diff(
        source_text.splitlines(keepends=True), timed_text.splitlines(keepends=True),
        fromfile="locked-final-room_finder.cpp", tofile="room_finder_timed.cpp")
    (out / "room_finder_timed.diff").write_text("".join(diff), encoding="utf-8")

    flags: dict[str, list[str]] = {}
    for line in FLAGS_PATH.read_text(encoding="utf-8").splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            flags[key] = shlex.split(value)
    object_path = out / "room_finder.cpp.o"
    compile_command = [
        "/usr/bin/c++", *flags["CXX_DEFINES"], *flags["CXX_INCLUDES"],
        *flags["CXX_FLAGS"], "-c", str(generated_source), "-o", str(object_path),
    ]
    link_command = shlex.split(LINK_PATH.read_text(encoding="utf-8").strip())
    link_command[link_command.index("-o") + 1] = str(dso_path)
    replacement = "CMakeFiles/hydra.dir/src/rooms/room_finder.cpp.o"
    if link_command.count(replacement) != 1:
        raise RuntimeError("Hydra link command does not contain one RoomFinder object slot")
    link_command = [str(object_path) if part == replacement else part for part in link_command]
    command_record = {
        "scope": "compile only timed replacement RoomFinder TU then relink existing Hydra objects",
        "input_lock_sha256": sha256(LOCK_PATH),
        "input_lock_revision": lock.get("lock_revision", 1),
        "superseded_input_lock_sha256": lock.get("input_lock_default_config_attempt_sha256"),
        "commands": [compile_command, link_command],
        "compile_cwd": str(ROOT),
        "link_cwd": str(BUILD_DIR),
        "output_dso": str(dso_path.resolve()),
        "stable_reference_dso": str(stable_resolved),
        "stable_reference_sha256": EXPECTED_STABLE_DSO_SHA256,
        "base_room_finder_sha256": base_sha,
        "generated_tu_sha256": sha256(generated_source),
        "flags_make_sha256": sha256(FLAGS_PATH),
        "link_txt_sha256": sha256(LINK_PATH),
    }
    (out / "build-commands.json").write_text(
        json.dumps(command_record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with (out / "build.log").open("w", encoding="utf-8") as log:
        for command, cwd in ((compile_command, ROOT), (link_command, BUILD_DIR)):
            completed = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
            if completed.returncode:
                (out / "build.exit").write_text(f"{completed.returncode}\n", encoding="ascii")
                return completed.returncode
    dso_sha = sha256(dso_path)
    if dso_sha == EXPECTED_STABLE_DSO_SHA256:
        raise RuntimeError("timed DSO unexpectedly equals the stable reference DSO")
    (out / "build.json").write_text(json.dumps({
        **command_record,
        "timed_dso_sha256": dso_sha,
        "timing_scope": {
            "getBestComponents": "inclusive wall nanoseconds and invocation count; RAII across all returns",
            "findRooms": "inclusive wall nanoseconds and invocation count; includes getBestComponents",
            "timers_are_nested": True,
        },
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (out / "build.exit").write_text("0\n", encoding="ascii")
    print(json.dumps({"timed_dso": str(dso_path.resolve()), "sha256": dso_sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
