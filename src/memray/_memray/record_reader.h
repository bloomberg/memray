#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <assert.h>
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
using location_id_t = size_t;

class RecordReader
{
  public:
    enum class RecordResult {
        ALLOCATION_RECORD,
        AGGREGATED_ALLOCATION_RECORD,
        MEMORY_RECORD,
        MEMORY_SNAPSHOT,
        OBJECT_RECORD,
        ERROR,
        END_OF_FILE,
    };
    explicit RecordReader(
            std::unique_ptr<memray::io::Source> source,
            bool track_stacks = true,
            bool track_object_lifetimes = false);
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
    std::optional<location_id_t> getLatestPythonLocationId(const Allocation& allocation);
    PyObject* Py_GetLocation(std::optional<location_id_t> frame);

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
    TrackedObject getLatestObject() const noexcept;

  private:
    // Aliases
    using stack_t = std::vector<FrameTree::index_t>;
    using stack_traces_t = std::unordered_map<thread_id_t, stack_t>;

    // Private methods
    void readHeader(HeaderRecord& header);
    template<typename T>
    bool readVarint(T* val);
    bool readVarint(uint64_t* val);
    template<typename T>
    bool readSignedVarint(T* val);
    bool readSignedVarint(int64_t* val);
    template<typename T>
    bool readIntegralDelta(T* cache, T* new_val);
    Location frameToLocation(frame_id_t frame);
    void extractRecordTypeAndFlags(
            unsigned char record_type_and_flags,
            RecordType* record_type,
            unsigned char* flags) const;
    RecordResult nextRecordFromAllAllocationsFile();
    RecordResult nextRecordFromAggregatedAllocationsFile();
    PyObject* dumpAllRecordsFromAllAllocationsFile();
    PyObject* dumpAllRecordsFromAggregatedAllocationsFile();

    // Data members
    mutable std::mutex d_mutex;
    std::unique_ptr<memray::io::Source> d_input;
    const bool d_track_stacks;
    const bool d_track_object_lifetimes;
    HeaderRecord d_header;
    std::unordered_map<code_object_id_t, CodeObjectInfo> d_code_object_map{};
    stack_traces_t d_stack_traces{};
    FrameTree d_tree{};
    Registry<Frame> d_python_frame_registry{};
    std::unordered_map<frame_id_t, Location> d_python_location_by_frame_id{};
    Registry<Location> d_location_registry{};

    mutable python_helpers::PyUnicode_Cache d_pystring_cache{};
    native_resolver::SymbolResolver d_symbol_resolver;
    std::vector<UnresolvedNativeFrame> d_native_frames{};
    // Pointer cache for recently seen addresses (LRU, indices 0-14)
    // The cache must stay synchronized with the writer's cache.
    // Index 0 = most recent, 14 = least recent
    // Cache encoding in allocation records:
    //   - 0x0 to 0xE (0-14): Cache hit at this index
    //   - 0xF (15): Cache miss, full address follows
    std::array<uintptr_t, 15> d_recent_addresses{};
    DeltaEncodedFields d_last;
    stack_t* d_curr_thread_stack{};

    std::unordered_map<thread_id_t, std::string> d_thread_names;
    Allocation d_latest_allocation;
    AggregatedAllocation d_latest_aggregated_allocation;
    MemoryRecord d_latest_memory_record{};
    MemorySnapshot d_latest_memory_snapshot{};
    TrackedObject d_latest_object;

    // Methods
    [[nodiscard]] bool parseFramePush(FramePush* record, unsigned int flags);
    [[nodiscard]] bool processFramePush(const FramePush& record);

    [[nodiscard]] static bool parseFramePop(FramePop* record, unsigned int flags);
    [[nodiscard]] bool processFramePop(const FramePop& record);

    [[nodiscard]] bool parseNativeFrameIndex(UnresolvedNativeFrame* frame);
    [[nodiscard]] bool processNativeFrameIndex(const UnresolvedNativeFrame& frame);

    [[nodiscard]] bool parseAllocationRecord(AllocationRecord* record, unsigned int flags);
    [[nodiscard]] bool processAllocationRecord(const AllocationRecord& record);

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

    [[nodiscard]] bool parsePythonFrameIndexRecord(std::pair<frame_id_t, Frame>* pyframe_val);
    [[nodiscard]] bool processPythonFrameIndexRecord(const std::pair<frame_id_t, Frame>& record);

    [[nodiscard]] bool parseCodeObjectRecord(tracking_api::pycode_map_val_t* pycode_val);
    [[nodiscard]] bool processCodeObjectRecord(const tracking_api::pycode_map_val_t& record);

    [[nodiscard]] bool parseObjectRecord(ObjectRecord* record, unsigned int flags);
    [[nodiscard]] bool processObjectRecord(const ObjectRecord& record);

    [[nodiscard]] bool parseSurvivingObjectRecord(ObjectRecord* record);
    [[nodiscard]] bool processSurvivingObjectRecord(const ObjectRecord& record);
};

template<typename T>
bool
RecordReader::readVarint(T* val)
{
    static_assert(std::is_unsigned<T>::value, "Only unsigned varints are supported");
    uint64_t temp;
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
    int64_t temp;
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
    int64_t delta;
    if (!readSignedVarint(&delta)) {
        return false;
    }
    *prev += delta;
    *new_val = *prev;
    return true;
}

}  // namespace memray::api
