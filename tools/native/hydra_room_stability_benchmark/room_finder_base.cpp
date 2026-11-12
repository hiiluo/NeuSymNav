/* -----------------------------------------------------------------------------
 * Copyright 2022 Massachusetts Institute of Technology.
 * All Rights Reserved
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 *  1. Redistributions of source code must retain the above copyright notice,
 *     this list of conditions and the following disclaimer.
 *
 *  2. Redistributions in binary form must reproduce the above copyright notice,
 *     this list of conditions and the following disclaimer in the documentation
 *     and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 * Research was sponsored by the United States Air Force Research Laboratory and
 * the United States Air Force Artificial Intelligence Accelerator and was
 * accomplished under Cooperative Agreement Number FA8750-19-2-1000. The views
 * and conclusions contained in this document are those of the authors and should
 * not be interpreted as representing the official policies, either expressed or
 * implied, of the United States Air Force or the U.S. Government. The U.S.
 * Government is authorized to reproduce and distribute reprints for Government
 * purposes notwithstanding any copyright notation herein.
 * -------------------------------------------------------------------------- */
#include "hydra/rooms/room_finder.h"

#include <glog/logging.h>
#include <spark_dsg/graph_utilities.h>

#include <Eigen/Dense>
#include <algorithm>
#include <queue>
#include <mutex>
#include <unordered_map>
#include <cmath>
#include <nlohmann/json.hpp>

namespace {
using Json = nlohmann::json;
struct PolicyConfig { bool enabled = false; int confirm = 3; double tolerance = .02; double epsilon = .0001; };
struct PolicyState { bool initialized = false; double accepted = 0; double pending = 0; int count = 0; uint64_t stamp = 0; };
std::mutex policy_mutex;
PolicyConfig policy;
std::unordered_map<const void*, PolicyState> states;
Json decision = {{"enabled", false}, {"action", "not_called"}};
}
extern "C" const char* nsn_room_stability_version() { return "neusymnav-room-stability-v1"; }
extern "C" int nsn_room_stability_configure(const char* text) {
  try {
    auto j = Json::parse(text ? text : "");
    if (!j.is_object() || !j.contains("enabled") || !j["enabled"].is_boolean()) return 1;
    for (auto it=j.begin(); it!=j.end(); ++it) if (it.key()!="enabled" && it.key()!="confirm_observations" && it.key()!="candidate_tolerance_m" && it.key()!="numerical_epsilon_m") return 1;
    PolicyConfig c; c.enabled=j.at("enabled").get<bool>();
    if(j.contains("confirm_observations")) { if(!j["confirm_observations"].is_number_integer()) return 1; c.confirm=j["confirm_observations"].get<int>(); }
    if(j.contains("candidate_tolerance_m")) { if(!j["candidate_tolerance_m"].is_number()) return 1; c.tolerance=j["candidate_tolerance_m"].get<double>(); }
    if(j.contains("numerical_epsilon_m")) { if(!j["numerical_epsilon_m"].is_number()) return 1; c.epsilon=j["numerical_epsilon_m"].get<double>(); }
    if(c.confirm!=3 || c.tolerance!=.02 || c.epsilon!=.0001) return 1;
    std::lock_guard<std::mutex> lock(policy_mutex); if(!states.empty()) return 2;
    policy=c; decision={{"enabled",c.enabled},{"action","configured"}}; return 0;
  } catch (...) { return 1; }
}
extern "C" const char* nsn_room_stability_last_decision() {
  thread_local std::string result; std::lock_guard<std::mutex> lock(policy_mutex); result=decision.dump(); return result.c_str();
}


#include "hydra/rooms/graph_filtration.h"
#include "hydra/rooms/room_utilities.h"

namespace hydra {

struct IndexTimePair {
  size_t index;
  uint64_t time_ns;

  bool operator>(const IndexTimePair& other) const { return time_ns > other.time_ns; }
};

using Cluster = ClusterResults::Cluster;
using Clusters = ClusterResults::Clusters;
using IndexTimePairQueue = std::priority_queue<IndexTimePair,
                                               std::vector<IndexTimePair>,
                                               std::greater<IndexTimePair>>;

void fillIndexQueue(const SceneGraphLayer& places,
                    const Clusters& clusters,
                    IndexTimePairQueue& queue,
                    size_t min_room_size) {
  for (const auto& id_cluster_pair : clusters) {
    if (id_cluster_pair.second.size() < min_room_size) {
      continue;
    }

    uint64_t oldest_time_ns = std::numeric_limits<uint64_t>::max();
    for (const auto& place : id_cluster_pair.second) {
      const auto& attrs = places.getNode(place).attributes();
      if (attrs.last_update_time_ns < oldest_time_ns) {
        oldest_time_ns = attrs.last_update_time_ns;
      }
    }

    queue.push({id_cluster_pair.first, oldest_time_ns});
  }
}

void logFiltration(std::ostream& fout,
                   const Filtration& filtration,
                   const std::pair<size_t, size_t>& window,
                   double distance) {
  fout << "{";
  fout << "\"start\":" << window.first << ",\"end\":" << window.second
       << ",\"threshold\":" << distance << ",\"filtration\":[";
  auto iter = filtration.begin();
  while (iter != filtration.end()) {
    fout << "{\"c\":" << iter->num_components << ",\"d\":" << iter->distance << "}";
    ++iter;
    if (iter != filtration.end()) {
      fout << ",";
    }
  }
  fout << "]},";
}

RoomFinder::RoomFinder(const RoomFinderConfig& config) : config_(config) {}

RoomFinder::~RoomFinder() {
  { std::lock_guard<std::mutex> lock(policy_mutex); states.erase(this); }
  if (log_file_) {
    if (logged_once_) {
      const size_t curr_pos = log_file_->tellp();
      log_file_->seekp(curr_pos - 1);
    }

    (*log_file_) << "]";
    if (graph_log_file_) {
      graph_log_file_->flush();
      graph_log_file_->close();
      graph_log_file_.reset();

      auto& fout = *log_file_;
      fout << ",\"offsets\":[";
      for (size_t i = 0; i < graph_entries_.size(); ++i) {
        const auto& entry = graph_entries_[i];
        fout << "{\"index\":" << i;
        fout << ",\"offset\":" << entry.offset;
        fout << ",\"size\":" << entry.size;
        fout << ",\"num_nodes\":" << entry.num_nodes;
        fout << ",\"num_edges\":" << entry.num_edges;
        fout << "}";
        if (i + 1 < graph_entries_.size()) {
          fout << ",";
        }
      }
      fout << "]";
    }

    (*log_file_) << "}" << std::endl;
    log_file_->flush();
    log_file_->close();
    log_file_.reset();
  }
}

void RoomFinder::enableLogging(const std::string& log_path) {
  if (!config_.log_filtrations) {
    return;
  }

  log_file_.reset(new std::ofstream(log_path + ".json"));
  (*log_file_) << "{\"contents\":[";

  if (!config_.log_place_graphs) {
    return;
  }

  const std::string gname = log_path + ".graphs";
  graph_log_file_.reset(new std::ofstream(gname, std::ios::binary));
}

InitialClusters RoomFinder::getBestComponents(const SceneGraphLayer& places) const {
  auto unavailable = [&](const char* action) {
    std::lock_guard<std::mutex> lock(policy_mutex);
    if (!policy.enabled) return;
    uint64_t stamp=0;
    for (const auto& entry : places.nodes()) stamp=std::max(stamp, entry.second->attributes().last_update_time_ns);
    auto& state=states[this];
    const bool novel=stamp>0 && stamp>state.stamp;
    if (novel) state.stamp=stamp;
    state.count=0;
    decision={{"enabled",true},{"action",action},{"timestamp_ns",stamp},{"novel_observation",novel},
              {"raw_threshold_m",nullptr},{"effective_threshold_m",nullptr},{"pending_count",0},
              {"raw_seed_count",0},{"selected_seed_count",0}};
  };
  BarcodeTracker tracker(config_.min_component_size);
  const auto filtration = getGraphFiltration(
      places,
      tracker,
      config_.dilation_diff_threshold_m,
      [this](const DisjointSet& components) -> size_t {
        size_t num_components = 0;
        for (const auto id_size_pair : components.sizes) {
          if (id_size_pair.second >= config_.min_component_size) {
            ++num_components;
          }
        }
        return num_components;
      },
      false);

  VLOG(10) << "[RoomFinder] Filtration: " << filtration;

  auto window = getTrimmedFiltration(filtration,
                                     config_.min_dilation_m,
                                     config_.max_dilation_m,
                                     config_.clip_dilation_window_to_max);
  if (window.first >= filtration.size()) {
    unavailable("unavailable_no_window");
    return {};
  }

  if (config_.clip_dilation_window_to_max) {
    const double window_size =
        filtration[window.second].distance - filtration[window.first].distance;
    if (window_size < config_.min_window_size) {
      VLOG(2) << "[RoomFinder] Bad window bounds: [" << config_.min_dilation_m << ", "
              << config_.max_dilation_m << "],  window: [" << window.first << ", "
              << window.second << "]"
              << " with size: " << window_size;

      window = getTrimmedFiltration(
          filtration, config_.min_dilation_m, config_.max_dilation_m, false);
    }
  }

  VLOG(2) << "[RoomFinder] Bounds: [" << config_.min_dilation_m << ", "
          << config_.max_dilation_m << "],  window: [" << window.first << ", "
          << window.second << "]";

  std::optional<FiltrationInfo> candidate = std::nullopt;
  switch (config_.dilation_threshold_mode) {
    case DilationThresholdMode::REPEATED:
      candidate = getLongestSequence(filtration, window.first, window.second);
      break;
    case DilationThresholdMode::LONGEST_LIFETIME:
      candidate = getLongestLifetimeDilation(filtration,
                                             tracker.barcodes,
                                             config_.min_lifetime_length_m,
                                             window.first,
                                             window.second);
      break;
    case DilationThresholdMode::PLATEAU:
    case DilationThresholdMode::PLATEAU_THRESHOLD:
    default:
      const bool use_threshold =
          config_.dilation_threshold_mode == DilationThresholdMode::PLATEAU_THRESHOLD;
      candidate = getBestPlateau(
          filtration,
          use_threshold ? config_.min_lifetime_length_m : config_.plateau_ratio,
          window.first,
          window.second,
          use_threshold);
      break;
  }

  if (!candidate) {
    unavailable("unavailable_no_candidate");
    return {};
  }

  const auto info = *candidate;
  VLOG(2) << "[RoomFinder] Best threshold: " << info.distance << " ("
          << info.num_components << " components)";

  if (log_file_) {
    if (graph_log_file_) {
      LOG(FATAL) << "Not implemented currently";
      /* const auto bson_str = places.toBson();*/
      /* graph_entries_.push_back(*/
      /*{graph_offset_, bson_str.size(), places.numNodes(), places.numEdges()});*/
      /*graph_log_file_->write(bson_str.data(), bson_str.size());*/
      /*graph_offset_ += bson_str.size();*/
    }

    logFiltration(*log_file_, filtration, window, info.distance);
    logged_once_ = true;
  }

  auto compute = [&](double threshold) {
    const auto components = graph_utilities::getConnectedComponents(
        places,
        [&](const SceneGraphNode& node) { return node.attributes<PlaceNodeAttributes>().distance > threshold; },
        [&](const SceneGraphEdge& edge) { return edge.info->weight > threshold; });
    InitialClusters filtered;
    for (const auto& component : components) if (component.size() >= config_.min_component_size) filtered.push_back(component);
    return filtered;
  };
  auto filtered = compute(info.distance);
  std::lock_guard<std::mutex> lock(policy_mutex);
  if (policy.enabled) {
    uint64_t stamp=0;
    for (const auto& entry : places.nodes()) stamp=std::max(stamp, entry.second->attributes().last_update_time_ns);
    auto& state=states[this];
    const bool novel=stamp>0 && stamp>state.stamp;
    const size_t raw_count=filtered.size();
    double effective=info.distance;
    std::string action;
    if (filtered.empty()) { state.count=0; action="unavailable_no_raw_support"; }
    else if (!state.initialized) { state.initialized=true; state.accepted=info.distance; state.count=0; action="bootstrap"; }
    else if (std::abs(info.distance-state.accepted)<=policy.epsilon) {
      state.accepted=info.distance; if (novel) state.count=0; action="follow_numerical_jitter";
    } else {
      if (novel) {
        if (state.count && std::abs(info.distance-state.pending)<=policy.tolerance) ++state.count;
        else { state.pending=info.distance; state.count=1; }
      }
      if (state.count>=policy.confirm) { state.accepted=info.distance; state.count=0; action="adopt"; }
      else {
        effective=state.accepted;
        double best=policy.epsilon;
        for (const auto& event : filtration) { const double delta=std::abs(event.distance-state.accepted); if(delta<=best) { best=delta; effective=event.distance; } }
        auto held=compute(effective);
        if (held.empty()) { state.accepted=info.distance; state.count=0; effective=info.distance; action="fallback_raw_no_held_support"; }
        else { filtered=std::move(held); action="hold"; }
      }
    }
    if (novel) state.stamp=stamp;
    decision={{"enabled",true},{"action",action},{"timestamp_ns",stamp},{"novel_observation",novel},{"raw_threshold_m",info.distance},{"effective_threshold_m",effective},{"pending_count",state.count},{"raw_seed_count",raw_count},{"selected_seed_count",filtered.size()}};
  }

  return filtered;
}

SceneGraphLayer::Ptr RoomFinder::findRooms(const SceneGraphLayer& places) {
  VLOG(2) << "[Room Finder] Detecting rooms for " << places.numNodes() << " nodes";

  const auto components = getBestComponents(places);
  if (components.empty()) {
    VLOG(2) << "[Room Finder] No rooms found";
    return nullptr;
  }

  last_results_.clear();
  switch (config_.clustering_mode) {
    case RoomClusterMode::MODULARITY:
      last_results_ = clusterGraphByModularity(
          places, components, config_.max_modularity_iters, config_.modularity_gamma);
      break;
    case RoomClusterMode::MODULARITY_DISTANCE:
      last_results_ = clusterGraphByModularity(
          places,
          components,
          [](const SceneGraphLayer& G, NodeId n1, NodeId n2) {
            // weight should be 1 / distance
            return 1.0 / (getNodePosition(G, n1) - getNodePosition(G, n2)).norm();
          },
          config_.max_modularity_iters,
          config_.modularity_gamma);
      break;
    case RoomClusterMode::NEIGHBORS:
      last_results_ = clusterGraphByNeighbors(places, components);
      break;
    case RoomClusterMode::NONE:
    default:
      last_results_.fillFromInitialClusters(components);
      break;
  }

  if (!last_results_.valid) {
    LOG(WARNING) << "[Room Finder] clustering failed: using components";
    last_results_.fillFromInitialClusters(components);
  }

  cluster_room_map_.clear();
  return makeRoomLayer(places);
}

SceneGraphLayer::Ptr RoomFinder::makeRoomLayer(const SceneGraphLayer& places) {
  SceneGraphLayer::Ptr rooms(new SceneGraphLayer(DsgLayers::ROOMS));

  // organize rooms by their oldest place
  IndexTimePairQueue queue;
  fillIndexQueue(places, last_results_.clusters, queue, config_.min_room_size);

  NodeSymbol room_id(config_.room_prefix, 0);
  while (!queue.empty()) {
    const auto cluster_index = queue.top().index;
    queue.pop();

    cluster_room_map_[cluster_index] = room_id;
    const auto& cluster = last_results_.clusters.at(cluster_index);

    auto attrs = std::make_unique<RoomNodeAttributes>();
    // TODO(nathan) define unknown label somewhere
    attrs->semantic_label = 0;
    attrs->position = getRoomPosition(places, cluster);

    rooms->emplaceNode(room_id, std::move(attrs));
    ++room_id;
  }

  addEdgesToRoomLayer(places, last_results_.labels, cluster_room_map_, *rooms);
  return rooms;
}

void RoomFinder::addRoomPlaceEdges(DynamicSceneGraph& graph) const {
  for (const auto& id_node_pair : graph.getLayer(DsgLayers::PLACES).nodes()) {
    const auto cluster = last_results_.labels.find(id_node_pair.first);
    if (cluster == last_results_.labels.end()) {
      continue;
    }

    const auto room = cluster_room_map_.find(cluster->second);
    if (room == cluster_room_map_.end()) {
      continue;
    }

    // add edge enforcing parent invariants
    graph.insertEdge(room->second, id_node_pair.first, nullptr, true);
  }
}

void RoomFinder::fillClusterMap(const SceneGraphLayer& places,
                                ClusterMap& assignments) const {
  assignments.clear();
  for (const auto& id_node_pair : places.nodes()) {
    const auto place_id = id_node_pair.first;

    const auto cluster = last_results_.labels.find(place_id);
    if (cluster == last_results_.labels.end()) {
      continue;
    }

    const auto room = cluster_room_map_.find(cluster->second);
    if (room == cluster_room_map_.end()) {
      continue;
    }

    const auto room_id = room->second;
    auto assignment = assignments.find(room_id);
    if (assignment == assignments.end()) {
      assignment = assignments.emplace(room_id, std::vector<NodeId>()).first;
    }

    assignment->second.push_back(place_id);
  }
}

}  // namespace hydra
