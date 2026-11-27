// Reuse the pinned upstream mesh-delta fixtures and run their existing tests too.
#include "test_mesh_segmenter.cpp"

#include "hydra/backend/merge_tracker.h"
#include "hydra/common/object_event_journal.h"

namespace hydra {
namespace {

TEST(ObjectEventJournal, RejectsLostOrUnconfirmedBatch) {
  ObjectEventJournal journal(1);
  const ObjectEvent event{ObjectEventOwner::Frontend, ObjectEventOperation::Create,
                          "O0"_id, std::nullopt};
  journal.record(event);
  EXPECT_FALSE(journal.finish(true));
  journal.begin();
  journal.record(event);
  journal.record(event);
  journal.confirm(ObjectEventOwner::Frontend, 15, 4);
  journal.confirm(ObjectEventOwner::Backend, 15, 4);
  EXPECT_FALSE(journal.finish(true, 15));
  journal.begin();
  journal.record(event);
  journal.confirm(ObjectEventOwner::Frontend, 15, 4);
  journal.confirm(ObjectEventOwner::Backend, 14, 4);
  EXPECT_FALSE(journal.finish(true, 15));
  journal.begin();
  journal.record(event);
  journal.confirm(ObjectEventOwner::Frontend, 15, 4);
  journal.confirm(ObjectEventOwner::Backend, 15, 3);
  EXPECT_FALSE(journal.finish(true, 15));
  journal.begin();
  journal.record(event);
  journal.confirm(ObjectEventOwner::Frontend, 15, 4);
  EXPECT_FALSE(journal.finish(true, 15));
  journal.begin();
  journal.record(event);
  journal.confirm(ObjectEventOwner::Frontend, 15, 4);
  journal.confirm(ObjectEventOwner::Backend, 15, 4);
  EXPECT_FALSE(journal.finish(false, 15));
  journal.begin();
  journal.record(event);
  journal.confirm(ObjectEventOwner::Frontend, 15, 4);
  journal.confirm(ObjectEventOwner::Backend, 15, 4);
  const auto batch = journal.finish(true, 15);
  ASSERT_TRUE(batch);
  ASSERT_EQ(batch->size(), 1u);
}

TEST(ObjectEventJournal, FrontendCapturesCreateAndPrune) {
  const auto journal = std::make_shared<ObjectEventJournal>();
  const auto dims = Eigen::Vector3f::Constant(0.1);
  MeshSegmenter::Config config;
  config.clustering.min_cluster_size = 4;
  MeshSegmenter segmenter(config, {1, 2});
  segmenter.setObjectEventJournal(journal);
  DynamicSceneGraph graph;
  graph.setMesh(std::make_shared<spark_dsg::Mesh>());
  kimera_pgmo::MeshOffsetInfo offsets;

  journal->begin();
  MeshDelta initial({0, 0, 0});
  addPoints(initial, 1, {1, 2, 3}, dims);
  addPoints(initial, 2, {4, 5, 6}, dims);
  stepSegmenter(initial, offsets, segmenter, graph);
  const auto created = journal->finish(true);
  ASSERT_TRUE(created);
  ASSERT_EQ(created->size(), 2u);
  for (const auto& event : *created) {
    EXPECT_EQ(event.owner, ObjectEventOwner::Frontend);
    EXPECT_EQ(event.operation, ObjectEventOperation::Create);
    EXPECT_FALSE(event.target);
    EXPECT_TRUE(graph.hasNode(event.source));
  }

  journal->begin();
  std::map<size_t, size_t> remap;
  for (size_t i = 0; i < 8; ++i) {
    remap[i + 8] = i;
  }
  MeshDelta single(MeshDelta::TrackingInfo::with_remap(0, 16, 0, remap));
  addPoints(single, 2, {4, 5, 6}, dims);
  stepSegmenter(single, offsets, segmenter, graph);
  const auto pruned = journal->finish(true);
  ASSERT_TRUE(pruned);
  ASSERT_EQ(pruned->size(), 1u);
  EXPECT_EQ(pruned->front().operation, ObjectEventOperation::Delete);
  EXPECT_EQ(pruned->front().source, "O0"_id);
  EXPECT_FALSE(pruned->front().target);
  EXPECT_FALSE(graph.hasNode("O0"_id));
}

TEST(ObjectEventJournal, FrontendMergeRecordsDestination) {
  const auto journal = std::make_shared<ObjectEventJournal>();
  const auto dims = Eigen::Vector3f::Constant(0.1);
  MeshSegmenter::Config config;
  config.clustering.min_cluster_size = 4;
  MeshSegmenter segmenter(config, {1});
  segmenter.setObjectEventJournal(journal);
  DynamicSceneGraph graph;
  graph.setMesh(std::make_shared<spark_dsg::Mesh>());
  kimera_pgmo::MeshOffsetInfo offsets;
  MeshDelta initial({0, 0, 0});
  addPoints(initial, 1, {1, 2, 3}, dims);
  addPoints(initial, 1, {4, 5, 6}, dims);
  stepSegmenter(initial, offsets, segmenter, graph);
  ASSERT_TRUE(graph.hasNode("O0"_id));
  ASSERT_TRUE(graph.hasNode("O1"_id));

  // Trigger the owner's native containment rule, with both nodes kept active.
  graph.getNode("O1"_id).attributes().position = graph.getNode("O0"_id).attributes().position;
  std::map<size_t, size_t> remap;
  for (size_t i = 0; i < 16; ++i) {
    remap[i] = i;
  }
  MeshDelta moved(MeshDelta::TrackingInfo::with_remap(0, 16, 0, remap));
  addPoints(moved, 1, {1, 2, 3}, dims);
  addPoints(moved, 1, {4, 5, 6}, dims);

  journal->begin();
  stepSegmenter(moved, offsets, segmenter, graph);
  const auto merged = journal->finish(true);
  ASSERT_TRUE(merged);
  ASSERT_FALSE(merged->empty());
  const auto& event = merged->front();
  EXPECT_EQ(event.owner, ObjectEventOwner::Frontend);
  EXPECT_EQ(event.operation, ObjectEventOperation::Merge);
  EXPECT_EQ(event.source, "O1"_id);
  EXPECT_EQ(event.target, "O0"_id);
  EXPECT_FALSE(graph.hasNode("O1"_id));
}

TEST(ObjectEventJournal, BackendRecordsRemappedSuccessfulObjectMerges) {
  const auto journal = std::make_shared<ObjectEventJournal>();
  MergeTracker tracker;
  tracker.setObjectEventJournal(journal);
  SharedDsgInfo dsg(SharedDsgInfo::Config{});
  for (const auto id : {"O0"_id, "O1"_id, "O2"_id}) {
    ASSERT_TRUE(dsg.graph->emplaceNode(2, id, std::make_unique<ObjectNodeAttributes>()));
  }
  const auto unmerged = dsg.graph->clone();

  journal->begin();
  EXPECT_EQ(tracker.applyMerges(*unmerged, {{"O0"_id, "O1"_id},
      {"O0"_id, "O1"_id}, {"O0"_id, "O2"_id}, {"O3"_id, "O2"_id}}, dsg), 2u);
  const auto batch = journal->finish(true);
  ASSERT_TRUE(batch);
  ASSERT_EQ(batch->size(), 2u);
  EXPECT_EQ(batch->at(0).owner, ObjectEventOwner::Backend);
  EXPECT_EQ(batch->at(0).operation, ObjectEventOperation::Merge);
  EXPECT_EQ(batch->at(0).source, "O0"_id);
  EXPECT_EQ(batch->at(0).target, "O1"_id);
  EXPECT_EQ(batch->at(1).source, "O1"_id);
  EXPECT_EQ(batch->at(1).target, "O2"_id);
  EXPECT_FALSE(dsg.graph->hasNode("O0"_id));
  EXPECT_FALSE(dsg.graph->hasNode("O1"_id));
  EXPECT_TRUE(dsg.graph->hasNode("O2"_id));
}

}  // namespace
}  // namespace hydra
