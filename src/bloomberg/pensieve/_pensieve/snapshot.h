#pragma once

#include <functional>
#include <unordered_map>
#include <vector>

#include "Python.h"

#include "frame_tree.h"
#include "interval_tree.h"
#include "records.h"

namespace pensieve::api {

using namespace tracking_api;

namespace {

const thread_id_t NO_THREAD_INFO = 0;

struct index_thread_pair_hash
{
    std::size_t operator()(const std::pair<FrameTree::index_t, thread_id_t>& p) const
    {
        // The indices and thread IDs are not likely to match as they are fundamentally different
        // values and have different ranges, so xor should work here and not cause duplicate hashes.
        return std::hash<FrameTree::index_t>{}(p.first) xor std::hash<thread_id_t>{}(p.second);
    }
};

}  // namespace

using allocations_t = std::vector<Allocation>;
using reduced_snapshot_map_t = std::
        unordered_map<std::pair<FrameTree::index_t, thread_id_t>, Allocation, index_thread_pair_hash>;

struct HighWatermark
{
    size_t index{0};
    size_t peak_memory{0};
};

HighWatermark
getHighWatermark(const allocations_t& sum);

PyObject*
Py_GetSnapshotAllocationRecords(
        const allocations_t& all_records,
        size_t record_index,
        bool merge_threads);

}  // namespace pensieve::api
