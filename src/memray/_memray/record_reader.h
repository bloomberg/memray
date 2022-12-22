#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
#include <fstream>
#include <functional>
#include <limits>
#include <memory>
#include <optional>
#include <stddef.h>
#include <stdint.h>
#include <string>
#include <unordered_map>
#include <vector>

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
        AGGREGATED_ALLOCATION_RECORD,
        MEMORY_RECORD,
        MEMORY_SNAPSHOT,
        ERROR,
        END_OF_FILE,
    };
    explicit RecordReader(std::unique_ptr<memray::io::Source> source, bool track_stacks = true);
    void close() noexcept;
    bool isOpen() const noexcept;
    PyObject*
    Py_GetStackFrame(FrameTree::index_t index, size_t max_stacks = std::numeric_limits<size_t>::max());
    PyObject* Py_GetStackFrameAndEntryInfo(
            FrameTree::index_t index,
            std::vector<unsigned char>* is_entry_frame,
            size_t max_stacks = std::numeric_limits<size_t>::max());
    PyObject* Py_GetNativeStackFrame(
            FrameTree::index_t index,
            size_t generation,
            size_t max_stacks = std::numeric_limits<size_t>::max());
    std::optional<frame_id_t> getLatestPythonFrameId(const Allocation& allocation) const;
    PyObject* Py_GetFrame(std::optional<frame_id_t> frame);

    RecordResult nextRecord();
    HeaderRecord getHeader() const noexcept;
    thread_id_t getMainThreadTid() const noexcept;
    size_t getSkippedFramesOnMainThread() const noexcept;
    PyObject* dumpAllRecords();
    std::string getThreadName(thread_id_t tid);
    Allocation getLatestAllocation() const noexcept;
    MemoryRecord getLatestMemoryRecord() const noexcept;
    AggregatedAllocation getLatestAggregatedAllocation() const noexcept;
    MemorySnapshot getLatestMemorySnapshot() const noexcept;

  private:
    // Aliases
    using stack_t = std::vector<FrameTree::index_t>;
    using stack_traces_t = std::unordered_map<thread_id_t, stack_t>;

    // Private methods
    void readHeader(HeaderRecord& header);
    template<typename T>
    bool readVarint(T* val);
    bool readVarint(size_t* val);
    template<typename T>
    bool readSignedVarint(T* val);
    bool readSignedVarint(ssize_t* val);
    template<typename T>
    bool readIntegralDelta(T* cache, T* new_val);
    RecordResult nextRecordFromAllAllocationsFile();
    RecordResult nextRecordFromAggregatedAllocationsFile();
    PyObject* dumpAllRecordsFromAllAllocationsFile();
    PyObject* dumpAllRecordsFromAggregatedAllocationsFile();

    // Data members
    mutable std::mutex d_mutex;
    std::unique_ptr<memray::io::Source> d_input;
    const bool d_track_stacks;
    HeaderRecord d_header;
    pyframe_map_t d_frame_map{};
    stack_traces_t d_stack_traces{};
    FrameTree d_tree{};
    mutable python_helpers::PyUnicode_Cache d_pystring_cache{};
    native_resolver::SymbolResolver d_symbol_resolver;
    std::vector<UnresolvedNativeFrame> d_native_frames{};
    DeltaEncodedFields d_last;
    std::unordered_map<thread_id_t, std::string> d_thread_names;
    Allocation d_latest_allocation;
    AggregatedAllocation d_latest_aggregated_allocation;
    MemoryRecord d_latest_memory_record{};
    MemorySnapshot d_latest_memory_snapshot{};

    // Methods
    [[nodiscard]] bool parseFramePush(FramePush* record);
    [[nodiscard]] bool processFramePush(const FramePush& record);

    [[nodiscard]] static bool parseFramePop(FramePop* record, unsigned int flags);
    [[nodiscard]] bool processFramePop(const FramePop& record);

    [[nodiscard]] bool parseFrameIndex(tracking_api::pyframe_map_val_t* pyframe_val, unsigned int flags);
    [[nodiscard]] bool processFrameIndex(const tracking_api::pyframe_map_val_t& pyframe_val);

    [[nodiscard]] bool parseNativeFrameIndex(UnresolvedNativeFrame* frame);
    [[nodiscard]] bool processNativeFrameIndex(const UnresolvedNativeFrame& frame);

    [[nodiscard]] bool parseAllocationRecord(AllocationRecord* record, unsigned int flags);
    [[nodiscard]] bool processAllocationRecord(const AllocationRecord& record);

    [[nodiscard]] bool parseNativeAllocationRecord(NativeAllocationRecord* record, unsigned int flags);
    [[nodiscard]] bool processNativeAllocationRecord(const NativeAllocationRecord& record);

    [[nodiscard]] static bool parseMemoryMapStart();
    [[nodiscard]] bool processMemoryMapStart();

    [[nodiscard]] bool parseSegmentHeader(std::string* filename, size_t* num_segments, uintptr_t* addr);
    [[nodiscard]] bool
    processSegmentHeader(const std::string& filename, size_t num_segments, uintptr_t addr);

    [[nodiscard]] bool parseSegment(Segment* segment);

    [[nodiscard]] bool parseThreadRecord(std::string* name);
    [[nodiscard]] bool processThreadRecord(const std::string& name);

    [[nodiscard]] bool parseMemoryRecord(MemoryRecord* record);
    [[nodiscard]] bool processMemoryRecord(const MemoryRecord& record);

    [[nodiscard]] bool parseContextSwitch(thread_id_t* tid);
    [[nodiscard]] bool processContextSwitch(thread_id_t tid);

    [[nodiscard]] bool parseMemorySnapshotRecord(MemorySnapshot* record);
    [[nodiscard]] bool processMemorySnapshotRecord(const MemorySnapshot& record);

    [[nodiscard]] bool parseAggregatedAllocationRecord(AggregatedAllocation* record);
    [[nodiscard]] bool processAggregatedAllocationRecord(const AggregatedAllocation& record);

    [[nodiscard]] bool parsePythonTraceIndexRecord(std::pair<frame_id_t, FrameTree::index_t>* record);
    [[nodiscard]] bool processPythonTraceIndexRecord(const std::pair<frame_id_t, FrameTree::index_t>&);

    [[nodiscard]] bool parsePythonFrameIndexRecord(tracking_api::pyframe_map_val_t* pyframe_val);
    [[nodiscard]] bool processPythonFrameIndexRecord(const tracking_api::pyframe_map_val_t& record);

    size_t getAllocationFrameIndex(const AllocationRecord& record);
};

template<typename T>
bool
RecordReader::readVarint(T* val)
{
    static_assert(std::is_unsigned<T>::value, "Only unsigned varints are supported");
    size_t temp;
    if (!readVarint(&temp)) {
        return false;
    }
    *val = temp;
    return true;
}

template<typename T>
bool
RecordReader::readSignedVarint(T* val)
{
    static_assert(!std::is_unsigned<T>::value, "Only signed varints are supported");
    ssize_t temp;
    if (!readSignedVarint(&temp)) {
        return false;
    }
    *val = temp;
    return true;
}

template<typename T>
bool
RecordReader::readIntegralDelta(T* prev, T* new_val)
{
    ssize_t delta;
    if (!readSignedVarint(&delta)) {
        return false;
    }
    *prev += delta;
    *new_val = *prev;
    return true;
}

}  // namespace memray::api
