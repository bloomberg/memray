#pragma once

#include <assert.h>
#include <fstream>
#include <functional>
#include <limits>
#include <memory>
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
#include "source.h"

namespace pensieve::api {

using namespace tracking_api;

using allocations_t = std::vector<Allocation>;

class RecordReader
{
  public:
    explicit RecordReader(std::unique_ptr<pensieve::io::Source> source);
    void close() noexcept;
    bool isOpen() const noexcept;
    PyObject*
    Py_GetStackFrame(FrameTree::index_t index, size_t max_stacks = std::numeric_limits<size_t>::max());
    PyObject* Py_GetNativeStackFrame(
            FrameTree::index_t index,
            size_t generation,
            size_t max_stacks = std::numeric_limits<size_t>::max());

    bool nextAllocationRecord(Allocation* allocation);
    HeaderRecord getHeader() const noexcept;

  private:
    // Aliases
    using stack_t = std::vector<frame_id_t>;
    using stack_traces_t = std::unordered_map<thread_id_t, stack_t>;
    using allocations_t = std::vector<Allocation>;

    // Private methods
    void readHeader(HeaderRecord& header);

    // Data members
    std::unique_ptr<pensieve::io::Source> d_input;
    HeaderRecord d_header;
    pyframe_map_t d_frame_map{};
    FrameCollection<Frame> d_allocation_frames{1, 2};
    stack_traces_t d_stack_traces{};
    FrameTree d_tree{};
    mutable python_helpers::PyUnicode_Cache d_pystring_cache{};
    native_resolver::SymbolResolver d_symbol_resolver;
    std::vector<UnresolvedNativeFrame> d_native_frames{};

    // Methods
    [[nodiscard]] bool parseFrame();
    [[nodiscard]] bool parseFrameIndex();
    [[nodiscard]] bool parseNativeFrameIndex();
    [[nodiscard]] bool parseAllocationRecord(AllocationRecord& record);
    [[nodiscard]] bool parseSegmentHeader();
    [[nodiscard]] bool parseSegment(Segment& segment);

    void correctAllocationFrame(stack_t& stack, int lineno);
    size_t getAllocationFrameIndex(const AllocationRecord& record);
};

}  // namespace pensieve::api
