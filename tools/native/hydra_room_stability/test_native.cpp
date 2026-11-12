#include <hydra/rooms/room_finder.h>
#include <spark_dsg/dynamic_scene_graph.h>
#include <spark_dsg/node_symbol.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <stdexcept>
#include <set>
using namespace hydra; using namespace spark_dsg; using J=nlohmann::json;
extern "C" int nsn_room_stability_configure(const char*);
extern "C" const char* nsn_room_stability_last_decision();
struct Finder:RoomFinder { using RoomFinder::RoomFinder; using RoomFinder::getBestComponents; };
void check(bool v,const char* msg){if(!v)throw std::runtime_error(msg);}
SceneGraphLayer::Ptr graph(double scale,uint64_t t, bool remove=false){
 auto g=std::make_shared<DynamicSceneGraph>();
 for(size_t i=0;i<32;++i){auto a=std::make_unique<PlaceNodeAttributes>();a->distance=remove?.05:1.3;a->position=Eigen::Vector3d((i/16)*5.+(i%4)*.3,((i%16)/4)*.3,1.0);a->last_update_time_ns=t;g->emplaceNode(DsgLayers::PLACES,NodeSymbol('p',i),std::move(a));}
 for(size_t base:{0u,16u})for(size_t i=0;i<16;++i)for(size_t j=i+1;j<16;++j){auto a=std::make_unique<EdgeAttributes>();a->weight=scale*(.75+.02*((i+j)%10));g->insertEdge(NodeSymbol('p',base+i),NodeSymbol('p',base+j),std::move(a));}
 auto a=std::make_unique<EdgeAttributes>();a->weight=.7*scale;g->insertEdge(NodeSymbol('p',15),NodeSymbol('p',16),std::move(a));return g->getLayer(DsgLayers::PLACES).clone();
}
J run(Finder& f,double scale,uint64_t t){auto g=graph(scale,t);auto seeds=f.getBestComponents(*g);auto d=J::parse(nsn_room_stability_last_decision());std::cout<<d.dump()<<"\n";check(!seeds.empty(),"no seeds");return d;}
int main(){try{
 const char* on=R"({"enabled":true,"confirm_observations":3,"candidate_tolerance_m":0.02,"numerical_epsilon_m":0.0001})";
 check(nsn_room_stability_configure(on)==0,"configure");RoomFinderConfig c;c.min_component_size=3;c.min_room_size=3;c.dilation_threshold_mode=DilationThresholdMode::PLATEAU;c.min_dilation_m=.1;c.max_dilation_m=1.2;c.clustering_mode=RoomClusterMode::NEIGHBORS;
 { Finder f(c);auto a=run(f,.8,1);check(a["action"]=="bootstrap","bootstrap");auto b=run(f,1,2);check(b["action"]=="hold" && b["pending_count"]==1 && b["selected_seed_count"]==1 && b["raw_seed_count"]==2,"spike hold and current merge");auto dup=run(f,1,2);check(dup["pending_count"]==1,"duplicate ages");auto back=run(f,.8,3);check(back["action"]=="follow_numerical_jitter","spike clears");run(f,1,4);run(f,1,5);
 auto missing=graph(1,6,true); auto none=f.getBestComponents(*missing); auto missing_d=J::parse(nsn_room_stability_last_decision()); std::cout<<missing_d.dump()<<"\n"; check(none.empty() && missing_d["pending_count"]==0 && missing_d["timestamp_ns"]==6,"unavailable interrupts confirmation");
 auto repeat=run(f,1,6);check(repeat["pending_count"]==0 && repeat["novel_observation"]==false,"unavailable consumes timestamp");
 run(f,1,7);run(f,1,8);auto adopted=run(f,1,9);check(adopted["action"]=="adopt" && adopted["selected_seed_count"]==2,"sustained split adoption"); }
 { Finder f(c);run(f,.8,10);run(f,1,11);run(f,1,12); SceneGraphLayer empty(DsgLayers::PLACES); auto seeds=f.getBestComponents(empty); auto d=J::parse(nsn_room_stability_last_decision()); std::cout<<d.dump()<<"\n";check(seeds.empty() && d["action"]=="unavailable_no_window" && d["pending_count"]==0 && d["timestamp_ns"]==0,"empty filtration resets and updates diagnostics"); auto next=run(f,1,13);check(next["pending_count"]==1,"empty filtration interrupted streak"); }
 { Finder f(c);auto a=run(f,1,7);check(a["action"]=="bootstrap","destructor reset"); auto b=run(f,.8,8); check(b["action"]=="fallback_raw_no_held_support" && b["selected_seed_count"]==b["raw_seed_count"],"no cached seeds on support loss"); }
 check(nsn_room_stability_configure(R"({"enabled":false})")==0,"disable");
 std::cout<<"PASS\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
