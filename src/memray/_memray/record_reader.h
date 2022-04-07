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

namespace memray::api {

using namespace tracking_api;

using allocations_t = std::vector<Allocation>;

class RecordReader
{
  public:
    enum class RecordResult {
        ALLOCATION_RECORD,
        MEMORY_RECORD,
        ERROR,
        END_OF_FILE,
    };
    explicit RecordReader(std::unique_ptr<memray::io::Source> source);
    void close() noexcept;
    bool isOpen() const noexcept;
    PyObject*
    Py_GetStackFrame(FrameTree::index_t index, size_t max_stacks = std::numeric_limits<size_t>::max());
    PyObject* Py_GetNativeStackFrame(
            FrameTree::index_t index,
            size_t generation,
            size_t max_stacks = std::numeric_limits<size_t>::max());

    RecordResult nextRecord();
    HeaderRecord getHeader() const noexcept;
    PyObject* dumpAllRecords();
    std::string getThreadName(thread_id_t tid);
    void clearRecords() noexcept;
    allocations_t& allocationRecords() noexcept;
    std::vector<MemoryRecord>& memoryRecords() noexcept;

  private:
    // Aliases
    using stack_t = std::vector<FrameTree::index_t>;
    using stack_traces_t = std::unordered_map<thread_id_t, stack_t>;

    // Private methods
    void readHeader(HeaderRecord& header);

    // Data members
    mutable std::mutex d_mutex;
    std::unique_ptr<memray::io::Source> d_input;
    HeaderRecord d_header;
    pyframe_map_t d_frame_map{};
    FrameCollection<Frame> d_allocation_frames{1, 2};
    stack_traces_t d_stack_traces{};
    FrameTree d_tree{};
    mutable python_helpers::PyUnicode_Cache d_pystring_cache{};
    native_resolver::SymbolResolver d_symbol_resolver;
    std::vector<UnresolvedNativeFrame> d_native_frames{};
    std::unordered_map<thread_id_t, std::string> d_thread_names;
    allocations_t d_allocation_records;
    std::vector<MemoryRecord> d_memory_records;

    // Methods
    [[nodiscard]] bool parseFramePush();
    [[nodiscard]] bool parseFramePop();
    [[nodiscard]] bool parseFrameIndex();
    [[nodiscard]] bool parseNativeFrameIndex();
    [[nodiscard]] bool parseAllocationRecord();
    [[nodiscard]] bool parseSegmentHeader();
    [[nodiscard]] bool parseSegment(Segment& segment);
    [[nodiscard]] bool parseThreadRecord();
    [[nodiscard]] bool parseMemoryRecord();

    size_t getAllocationFrameIndex(const AllocationRecord& record);
};

}  // namespace memray::api
