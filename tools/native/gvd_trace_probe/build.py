#!/usr/bin/env python3
"""Build a private, observational Hydra extractor library from the existing build."""
import hashlib, json, pathlib, shlex, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[3]
WS = ROOT / '.runtime/hydra_ws'
BUILD = WS / 'build/hydra'
OUT = ROOT / 'runs/hydra-objectnav/B1-support-20261107/native-probe'
SRC = WS / 'src/hydra/src/places/graph_extractor.cpp'
OUT.mkdir(parents=True, exist_ok=True)
s = SRC.read_text()
def replace(old, new):
    global s
    if s.count(old) != 1:
        raise RuntimeError(f'expected exactly one anchor: {old[:100]!r}, got {s.count(old)}')
    s = s.replace(old, new, 1)
replace('#include <config_utilities/config.h>', '''#include <config_utilities/config.h>
#include <cstdlib>
#include <fstream>
#include <nlohmann/json.hpp>

namespace {
using TraceJson = nlohmann::json;
thread_local std::ofstream* trace_stream = nullptr;
thread_local uint64_t trace_timestamp = 0;
void trace(TraceJson data) {
  if (!trace_stream) return;
  data["timestamp_ns"] = trace_timestamp;
  *trace_stream << data.dump() << '\\n';
}
template <typename V> TraceJson vec3(const V& x) {
  return TraceJson::array({x[0], x[1], x[2]});
}
}  // namespace
''')
replace('''  // 0(a). remove all archived nodes that no longer have active siblings
  clearArchived();''', '''  std::ofstream trace_file;
  const char* trace_path = std::getenv("HYDRA_GVD_TRACE_JSONL");
  if (trace_path && *trace_path) {
    trace_file.open(trace_path, std::ios::app);
    if (trace_file) { trace_stream = &trace_file; trace_timestamp = timestamp_ns; }
  }
  trace({{"kind", "begin"}, {"compression_distance_m", config.compression_distance_m},
         {"min_node_distance_m", config.min_node_distance_m},
         {"node_merge_distance_m", config.node_merge_distance_m},
         {"merge_nearby_nodes", config.merge_nearby_nodes}});
  auto snapshot = [&](const char* stage) {
    if (!trace_stream) return;
    for (const auto& [id, v] : gvd_->nodes()) {
      auto remap = compressed_remapping_.find(id);
      trace({{"kind", "gvd"}, {"stage", stage}, {"id", id},
             {"index", vec3(v.index)}, {"xyz", vec3(v.position)},
             {"clearance", v.distance}, {"basis", v.num_basis_points},
             {"siblings", v.siblings}, {"eligible_clearance", v.distance >= config.min_node_distance_m},
             {"compressed_id", remap == compressed_remapping_.end() ? TraceJson(nullptr) : TraceJson(remap->second)}});
    }
    for (const auto& [id, c] : compressed_info_map_) {
      const auto* best = gvd_->getNode(c.best_gvd_id);
      const auto place = getPlaceId(id);
      TraceJson j = {{"kind", "compressed"}, {"stage", stage}, {"id", id},
                     {"place_id", place}, {"in_graph", c.in_graph},
                     {"graph_has_node", graph_->hasNode(place)},
                     {"best_gvd_id", c.best_gvd_id}, {"active_refs", c.active_refs},
                     {"archived_refs", c.archived_refs}, {"siblings", c.siblings}};
      if (best) { j["xyz"] = vec3(best->position); j["index"] = vec3(best->index);
                  j["clearance"] = best->distance; j["basis"] = best->num_basis_points; }
      trace(std::move(j));
    }
    for (const auto& [id, node] : graph_->nodes()) {
      const auto& a = node->attributes<PlaceNodeAttributes>();
      trace({{"kind", "place"}, {"stage", stage}, {"id", id},
             {"xyz", vec3(a.position)}, {"clearance", a.distance},
             {"basis", a.num_basis_points}, {"siblings", node->siblings()}});
    }
  };
  // 0(a). remove all archived nodes that no longer have active siblings
  clearArchived();''')
replace('''  updateCompressedEdges(layer);

  // TODO''', '''  updateCompressedEdges(layer);
  snapshot("before_merge");

  // TODO''')
replace('''  updated_nodes_.clear();

  if (config.add_heuristic_edges)''', '''  snapshot("after_merge");
  updated_nodes_.clear();

  if (config.add_heuristic_edges)''')
replace('''  if (config.validate_graph) {
    validate(layer);
  }
}''', '''  if (config.validate_graph) {
    validate(layer);
  }
  snapshot("final");
  trace({{"kind", "end"}});
  trace_stream = nullptr;
}''')
replace('''    if (info.siblings.empty()) {
      to_delete.push_back''', '''    trace({{"kind", "updated_gvd"}, {"id", iter->second}, {"index", vec3(info.index)},
           {"xyz", vec3(info.position)}, {"clearance", info.distance},
           {"basis", info.num_basis_points}, {"siblings", info.siblings},
           {"eligible_clearance", info.distance >= config.min_node_distance_m},
           {"isolated_at_visit", info.siblings.empty()}});
    if (info.siblings.empty()) {
      to_delete.push_back''')
replace('''  for (const auto& from_to_pair : merges) {
    compressed_info_map_.at(from_to_pair.first).in_graph = false;''', '''  for (const auto& from_to_pair : merges) {
    trace({{"kind", "merge"}, {"from_compressed_id", from_to_pair.first},
           {"to_compressed_id", from_to_pair.second}});
    compressed_info_map_.at(from_to_pair.first).in_graph = false;''')
copy = OUT / 'graph_extractor.cpp'
copy.write_text(s)
flags = {}
for line in (BUILD / 'CMakeFiles/hydra.dir/flags.make').read_text().splitlines():
    if ' = ' in line:
        k,v = line.split(' = ',1); flags[k] = shlex.split(v)
obj = OUT / 'graph_extractor.cpp.o'
lib = OUT / 'libhydra.so'
compile_cmd = ['/usr/bin/c++', *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], *flags['CXX_FLAGS'], '-o', str(obj), '-c', str(copy)]
link_cmd = shlex.split((BUILD / 'CMakeFiles/hydra.dir/link.txt').read_text())
link_cmd[link_cmd.index('-o')+1] = str(lib)
old_obj = 'CMakeFiles/hydra.dir/src/places/graph_extractor.cpp.o'
assert link_cmd.count(old_obj) == 1
link_cmd[link_cmd.index(old_obj)] = str(obj)
(OUT / 'commands.json').write_text(json.dumps({'cwd': str(BUILD), 'compile':compile_cmd, 'link':link_cmd}, indent=2)+'\n')
for name, cmd in [('compile',compile_cmd),('link',link_cmd)]:
    with (OUT / f'{name}.log').open('w') as log:
        p = subprocess.run(cmd,cwd=BUILD,stdout=log,stderr=subprocess.STDOUT)
    (OUT / f'{name}.exit').write_text(str(p.returncode)+'\n')
    if p.returncode: raise SystemExit(p.returncode)
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
paths = [SRC, copy, obj, lib, WS/'install/hydra/lib/libhydra.so', BUILD/'CMakeFiles/hydra.dir/flags.make', BUILD/'CMakeFiles/hydra.dir/link.txt']
(OUT/'fingerprints.json').write_text(json.dumps({str(p):digest(p) for p in paths},indent=2)+'\n')
print(lib)
