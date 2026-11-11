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

int main(){RoomFinderConfig c;c.min_component_size=3;c.min_room_size=3;c.dilation_threshold_mode=DilationThresholdMode::PLATEAU;c.min_dilation_m=.1;c.max_dilation_m=1.2; Finder f(c);for(double scale:{.8,1.0,.9}) {auto g=graph(scale,1);auto seeds=f.getBestComponents(*g);std::set<std::set<NodeId>> ordered;for(auto& x:seeds)ordered.emplace(x.begin(),x.end());for(auto& x:ordered){std::cout<<"[";for(auto id:x)std::cout<<id<<",";std::cout<<"]";}std::cout<<"\n";} }
