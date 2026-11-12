// Offline diagnostic adapter. Calls installed Hydra algorithms unchanged.
// Never writes the input Spark-DSG or changes the production room configuration.
#include <hydra/rooms/room_finder.h>
#include <spark_dsg/dynamic_scene_graph.h>
#include <spark_dsg/graph_utilities.h>
#include <spark_dsg/node_symbol.h>
#include <config_utilities/parsing/yaml.h>
#include <nlohmann/json.hpp>
#include <yaml-cpp/yaml.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <cmath>
#include <algorithm>
#include <map>
#include <set>
using J=nlohmann::json;
using namespace hydra;
using namespace spark_dsg;
class InspectRoomFinder final: public RoomFinder {
 public:
  explicit InspectRoomFinder(const RoomFinderConfig& c):RoomFinder(c){}
  InitialClusters seeds(const SceneGraphLayer& p)const{return getBestComponents(p);}
  const ClusterResults& clusters()const{return last_results_;}
  const std::map<size_t,NodeId>& roomMap()const{return cluster_room_map_;}
  void precision(){if(log_file_)*log_file_<<std::setprecision(17);}
};
std::string name(NodeId id){return NodeSymbol(id).str();}
template<class C> J ids(const C& c){std::vector<std::string> v;for(auto id:c)v.push_back(name(id));std::sort(v.begin(),v.end());return v;}
DynamicSceneGraph::Ptr fixture(){
 auto g=std::make_shared<DynamicSceneGraph>();
 for(size_t i=0;i<32;++i){auto a=std::make_unique<PlaceNodeAttributes>();a->distance=1.3;
  a->position=Eigen::Vector3d((i/16)*5.+(i%4)*.3,((i%16)/4)*.3,1.0);
  a->last_update_time_ns=i+1;g->emplaceNode(DsgLayers::PLACES,NodeSymbol('p',i),std::move(a));}
 for(size_t base:{0u,16u})for(size_t i=0;i<16;++i)for(size_t j=i+1;j<16;++j){
  auto a=std::make_unique<EdgeAttributes>();a->weight=.75+.02*((i+j)%10);
  g->insertEdge(NodeSymbol('p',base+i),NodeSymbol('p',base+j),std::move(a));}
 auto a=std::make_unique<EdgeAttributes>();a->weight=.25;g->insertEdge(NodeSymbol('p',15),NodeSymbol('p',16),std::move(a));return g;
}
int main(int argc,char**argv){try{
 std::map<std::string,std::string> args;bool synthetic=false;
 for(int i=1;i<argc;++i){std::string k=argv[i];if(k=="--synthetic-two-room"){synthetic=true;continue;}
  if((k!="--graph"&&k!="--config"&&k!="--filtration-log")||i+1>=argc)throw std::runtime_error("invalid/missing argument: "+k);
  if(args.count(k))throw std::runtime_error("duplicate argument");
  args[k]=argv[++i];}
 if(!args.count("--config")||!args.count("--filtration-log")||(!synthetic&&!args.count("--graph"))||(synthetic&&args.count("--graph")))throw std::runtime_error("require --config --filtration-log and either --graph or --synthetic-two-room");
 auto yaml=YAML::LoadFile(args.at("--config"));auto node=yaml["backend"]["update_functors"]["rooms"]["room_finder"];
 auto cfg=config::fromYaml<RoomFinderConfig>(node);
 if(cfg.clustering_mode!=RoomClusterMode::NEIGHBORS||cfg.dilation_threshold_mode!=DilationThresholdMode::PLATEAU)throw std::runtime_error("diagnostic currently supports pinned NEIGHBORS/PLATEAU only");
 cfg.log_filtrations=true;cfg.log_place_graphs=false;
 auto graph=synthetic?fixture():DynamicSceneGraph::load(args.at("--graph"));
 auto places=graph->getLayer(DsgLayers::PLACES).clone([](const auto& n){return NodeSymbol(n.id).category()=='p';});
 J output={{"schema_version",1},{"scope","native_offline_reconstruction_from_frozen_final_graph"},{"synthetic",synthetic},{"places",J::array()},{"edges",J::array()}};
 std::map<NodeId,std::string> recorded;
 for(const auto& [id,np]:graph->getLayer(DsgLayers::PLACES).nodes()){
  auto p=np->getParent();if(p&&graph->hasNode(*p)&&graph->getNode(*p).layer==graph->getLayer(DsgLayers::ROOMS).id)recorded[id]=name(*p);}
 for(const auto& [id,np]:places->nodes()){
  const auto&a=np->attributes<PlaceNodeAttributes>();if(!std::isfinite(a.distance)||!a.position.allFinite())throw std::runtime_error("nonfinite place geometry");
  output["places"].push_back({{"id",name(id)},{"position_xyz",{a.position.x(),a.position.y(),a.position.z()}},{"clearance_m",a.distance},{"recorded_room_id",recorded.count(id)?J(recorded[id]):J(nullptr)}});}
 for(const auto& [key,ep]:places->edges()){
  if(!std::isfinite(ep.info->weight))throw std::runtime_error("nonfinite edge weight");
  output["edges"].push_back({{"source",name(ep.source)},{"target",name(ep.target)},{"weight_m",ep.info->weight}});}
 J rf={{"config",{{"min_dilation_m",cfg.min_dilation_m},{"max_dilation_m",cfg.max_dilation_m},{"min_component_size",cfg.min_component_size},{"min_room_size",cfg.min_room_size},{"dilation_threshold_mode","PLATEAU"},{"plateau_ratio",cfg.plateau_ratio},{"min_window_size",cfg.min_window_size},{"clip_dilation_window_to_max",cfg.clip_dilation_window_to_max},{"clustering_mode","NEIGHBORS"},{"dilation_diff_threshold_m",cfg.dilation_diff_threshold_m}}},{"seeds_before_neighbors",J::array()},{"post_neighbor_clusters",J::array()},{"raw_components",J::array()}};
 InitialClusters seeds;std::map<NodeId,std::string> reconstructed;
 {
  InspectRoomFinder finder(cfg);finder.enableLogging(args.at("--filtration-log"));finder.precision();seeds=finder.seeds(*places);
  const auto rooms=finder.findRooms(*places);rf["room_count"]=rooms?rooms->numNodes():0;
  for(size_t i=0;i<seeds.size();++i)rf["seeds_before_neighbors"].push_back({{"seed_id",i},{"place_ids",ids(seeds[i])},{"size",seeds[i].size()}});
  for(const auto& [index,c]:finder.clusters().clusters){
   auto r=finder.roomMap().find(index);J rid=r==finder.roomMap().end()?J(nullptr):J(name(r->second));
   J seed_ids=J::array();for(const auto& seed:seeds)for(auto id:seed)if(c.count(id))seed_ids.push_back(name(id));
   rf["post_neighbor_clusters"].push_back({{"cluster_index",index},{"place_ids",ids(c)},{"seed_place_ids",seed_ids},{"size",c.size()},{"accepted_as_room",r!=finder.roomMap().end()},{"room_id",rid}});
   if(r!=finder.roomMap().end())for(auto id:c)reconstructed[id]=name(r->second);
  }
 }
 std::ifstream file(args.at("--filtration-log")+".json");J log;file>>log;output["native_filtration_log"]=log;
 rf["selected_threshold_m"]=nullptr;
 if(log.contains("contents")&&!log["contents"].empty())rf["selected_threshold_m"]=log["contents"].back()["threshold"];
 if(!rf["selected_threshold_m"].is_null()){
  const double t=rf["selected_threshold_m"];
  const auto comps=graph_utilities::getConnectedComponents(*places,[&](const auto& n){return n.template attributes<PlaceNodeAttributes>().distance>t;},[&](const auto&e){return e.info->weight>t;});
  std::set<std::vector<std::string>> retained,native;
  for(const auto& s:seeds)native.insert(ids(s).get<std::vector<std::string>>());
  for(size_t i=0;i<comps.size();++i){J list=ids(comps[i]);bool keep=comps[i].size()>=cfg.min_component_size;
   rf["raw_components"].push_back({{"component_id",i},{"place_ids",list},{"size",comps[i].size()},{"retained_as_seed",keep}});
   if(keep)retained.insert(list.get<std::vector<std::string>>());}
  const auto unfiltered=clusterGraphByNeighbors(*places,comps);
  J counter=J::array();
  for(const auto& [index,c]:unfiltered.clusters){counter.push_back({{"cluster_index",index},{"place_ids",ids(c)},{"size",c.size()},{"passes_original_min_room_size",c.size()>=cfg.min_room_size}});}
  rf["counterfactual_unfiltered_component_propagation"]={{"scope","diagnostic_only_all_raw_components_as_seeds_not_original_roomfinder_output"},{"clusters",counter}};
  rf["raw_retained_matches_native_seeds"]=retained==native;
  if(retained!=native)throw std::runtime_error("threshold precision/raw components differ from native seeds");
 }
 size_t matched=0;for(const auto& [id,r]:recorded)if(reconstructed.count(id)&&reconstructed.at(id)==r)++matched;
 output["recorded_membership"]={{"assigned_count",recorded.size()},{"exactly_matching_reconstruction",matched},{"comparable",!synthetic}};
 output["room_finder"]=rf;output["quality_evidence"]={{"independent_room_annotation",nullptr}};
 std::cout<<output.dump(2)<<std::endl;return 0;
 }catch(const std::exception&e){std::cerr<<"room diagnostic: "<<e.what()<<std::endl;return 1;}}
