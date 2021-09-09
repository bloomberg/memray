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

using allocations_t = std::vector<Allocation>;

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
