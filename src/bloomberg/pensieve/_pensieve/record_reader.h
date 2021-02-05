#pragma once

#include <assert.h>
#include <fstream>
#include <functional>
#include <limits>
#include <stddef.h>
#include <stdint.h>
#include <string>
#include <unordered_map>
#include <vector>

#include "Python.h"

#include "frame_tree.h"
#include "native_resolver.h"
#include "python_helpers.h"
#include "records.h"

namespace pensieve::api {

using namespace tracking_api;

using reduced_snapshot_map_t = std::unordered_map<FrameTree::index_t, Allocation>;
using allocations_t = std::vector<Allocation>;

class RecordReader
{
  public:
    explicit RecordReader(const std::string& file_name);
    PyObject*
    Py_GetStackFrame(FrameTree::index_t index, size_t max_stacks = std::numeric_limits<size_t>::max());
    PyObject* Py_GetNativeStackFrame(
            FrameTree::index_t index,
            size_t generation,
            size_t max_stacks = std::numeric_limits<size_t>::max());

    bool nextAllocationRecord(Allocation* allocation);

    size_t totalAllocations() const noexcept;
    size_t totalFrames() const noexcept;

  private:
    // Aliases
    using stack_t = std::vector<frame_id_t>;
    using stack_traces_t = std::unordered_map<thread_id_t, stack_t>;
    using allocations_t = std::vector<Allocation>;

    // Data members
    std::ifstream d_input;
    HeaderRecord d_header;
    pyframe_map_t d_frame_map{};
    FrameCollection<Frame> d_allocation_frames;
    stack_traces_t d_stack_traces{};
    FrameTree d_tree{};
    mutable python_helpers::PyUnicode_Cache d_pystring_cache{};
    native_resolver::SymbolResolver d_symbol_resolver;
    std::vector<UnresolvedNativeFrame> d_native_frames{};

    // Methods
    void parseFrame();
    void parseFrameIndex();
    void parseNativeFrameIndex();
    AllocationRecord parseAllocationRecord();
    void parseSegmentHeader();
    Segment parseSegment();

    void correctAllocationFrame(stack_t& stack, int lineno);
    size_t getAllocationFrameIndex(const AllocationRecord& record);
};

PyObject*
Py_HighWatermarkAllocationRecords(const allocations_t& all_records);

}  // namespace pensieve::api
