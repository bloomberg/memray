#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <fstream>
#include <mutex>
#include <stddef.h>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

#include "hooks.h"
#include "python_helpers.h"

namespace memray::tracking_api {

extern const char MAGIC[7];  // Value assigned in records.cpp
const int CURRENT_HEADER_VERSION = 12;

using frame_id_t = size_t;
using thread_id_t = unsigned long;
using millis_t = long long;
using code_object_id_t = size_t;

// If the high (128) bit is set on a given record type discriminator,
// it's an ALLOCATION record with 7 bits available for flags (see
// "ALLOCATION ENCODING" in record_writer.cpp for details).
//
// Otherwise, if the 64 bit is set, it's a FRAME_PUSH record with 6 bits
// available for flags (see "FRAME_PUSH ENCODING" in record_writer.cpp).
//
// Otherwise, if the 16 bit is set, it's a FRAME_POP record with 4 bits
// available for flags (see "FRAME_POP ENCODING" in record_writer.cpp).
//
// Otherwise, it's a record type that has no flags, and all remaining
// bits identify the record type
enum class RecordType : unsigned char {
    FILLER = 0,
    TRAILER = 1,
    MEMORY_RECORD = 2,
    NATIVE_TRACE_INDEX = 5,
    MEMORY_MAP_START = 6,
    SEGMENT_HEADER = 7,
    SEGMENT = 8,
    THREAD_RECORD = 10,
    CONTEXT_SWITCH = 12,
    CODE_OBJECT = 14,

    FRAME_POP = 16,  // 16 through 31
    OBJECT_RECORD = 32,  // 32 through 63
    FRAME_PUSH = 64,  // 64 through 127
    ALLOCATION = 128,  // 128 through 255
};

// Enumerators that have the same name as in RecordType are encoded the same
// way and have the same enumeration value. Enumerators with different names
// have different encoded representations.
enum class AggregatedRecordType : unsigned char {
    MEMORY_SNAPSHOT = 1,
    AGGREGATED_ALLOCATION = 2,
    PYTHON_TRACE_INDEX = 3,
    PYTHON_FRAME_INDEX = 4,

    NATIVE_TRACE_INDEX = 5,
    MEMORY_MAP_START = 6,
    SEGMENT_HEADER = 7,
    SEGMENT = 8,
    THREAD_RECORD = 10,
    CONTEXT_SWITCH = 12,
    SURVIVING_OBJECT = 13,
    CODE_OBJECT = 14,

    AGGREGATED_TRAILER = 15,
};

struct TrackerStats
{
    size_t n_allocations{0};
    size_t n_frames{0};
    millis_t start_time{};
    millis_t end_time{};
};

enum PythonAllocatorType : unsigned char {
    PYTHONALLOCATOR_PYMALLOC = 1,
    PYTHONALLOCATOR_PYMALLOC_DEBUG = 2,
    PYTHONALLOCATOR_MALLOC = 3,
    PYTHONALLOCATOR_OTHER = 4,
    PYTHONALLOCATOR_MIMALLOC = 5,
    PYTHONALLOCATOR_MIMALLOC_DEBUG = 6,
};

enum FileFormat : unsigned char {
    ALL_ALLOCATIONS,
    AGGREGATED_ALLOCATIONS,
};

struct HeaderRecord
{
    char magic[sizeof(MAGIC)];
    int version{};
    int python_version{PY_VERSION_HEX};
    bool native_traces{false};
    FileFormat file_format{FileFormat::ALL_ALLOCATIONS};
    TrackerStats stats{};
    std::string command_line;
    int pid{-1};
    thread_id_t main_tid{};
    size_t skipped_frames_on_main_tid{};
    PythonAllocatorType python_allocator{};
    bool trace_python_allocators{};
    bool track_object_lifetimes{false};
};

struct MemoryRecord
{
    uint64_t ms_since_epoch;
    size_t rss;
};

struct MemorySnapshot
{
    uint64_t ms_since_epoch;
    size_t rss;
    size_t heap;
};

struct AllocationRecord
{
    uintptr_t address;
    size_t size;
    hooks::Allocator allocator;
    frame_id_t native_frame_id{0};
};

struct Allocation
{
    thread_id_t tid;
    uintptr_t address;
    size_t size;
    hooks::Allocator allocator;
    frame_id_t native_frame_id{0};
    size_t frame_index{0};
    size_t native_segment_generation{0};
    size_t n_allocations{1};

    PyObject* toPythonObject() const;
};

struct TrackedObject
{
    thread_id_t tid;
    uintptr_t address;
    bool is_created;
    frame_id_t native_frame_id{0};
    size_t frame_index{0};
    size_t native_segment_generation{0};

    PyObject* toPythonObject() const;
};

struct AggregatedAllocation
{
    thread_id_t tid;
    hooks::Allocator allocator;
    frame_id_t native_frame_id;
    size_t frame_index;
    size_t native_segment_generation;

    size_t n_allocations_in_high_water_mark;
    size_t n_allocations_leaked;
    size_t bytes_in_high_water_mark;
    size_t bytes_leaked;

    Allocation contributionToHighWaterMark() const;
    Allocation contributionToLeaks() const;
};

struct MemoryMapStart
{
};

struct SegmentHeader
{
    const char* filename;
    size_t num_segments;
    uintptr_t addr;
};

struct Segment
{
    uintptr_t vaddr;
    uintptr_t memsz;
};

struct ImageSegments
{
    std::string filename;
    uintptr_t addr;
    std::vector<Segment> segments;
};

struct Frame
{
    code_object_id_t code_object_id;
    int instruction_offset;
    bool is_entry_frame;

    auto operator==(const Frame& other) const -> bool
    {
        return (code_object_id == other.code_object_id && instruction_offset == other.instruction_offset
                && is_entry_frame == other.is_entry_frame);
    }

    struct Hash
    {
        auto operator()(memray::tracking_api::Frame const& frame) const noexcept -> std::size_t
        {
            return std::hash<uint64_t>()(frame.code_object_id)
                   ^ std::hash<int>()(frame.instruction_offset) ^ frame.is_entry_frame;
        }
    };
};

struct Location
{
    std::string function_name;
    std::string filename;
    int lineno{0};

    PyObject* toPythonObject(python_helpers::PyUnicode_Cache& pystring_cache) const;

    auto operator==(const Location& other) const -> bool
    {
        return (function_name == other.function_name && filename == other.filename
                && lineno == other.lineno);
    }

    struct Hash
    {
        auto operator()(const Location& location) const noexcept -> std::size_t
        {
            auto the_func = std::hash<std::string>{}(location.function_name);
            auto the_filename = std::hash<std::string>{}(location.filename);
            auto lineno = std::hash<int>{}(location.lineno);
            return the_func ^ the_filename ^ lineno;
        }
    };
};

// For storing code object info with strings (used in reader)
struct CodeObjectInfo
{
    std::string function_name;
    std::string filename;
    std::string linetable;
    int firstlineno;
};

using pycode_map_val_t = std::pair<code_object_id_t, CodeObjectInfo>;

// Structure to represent code object information
struct CodeObject
{
    const char* function_name;
    const char* filename;
    const char* linetable;
    size_t linetable_size;
    int firstlineno;
};

struct RawFrame
{
    PyCodeObject* code;
    CodeObject code_info;
    bool is_entry_frame;
    int instruction_offset;
};

struct FramePush
{
    Frame frame;
};

struct FramePop
{
    size_t count;
};

struct UnresolvedNativeFrame
{
    uintptr_t ip;
    size_t index;
};

struct ContextSwitch
{
    thread_id_t tid;
};

struct DeltaEncodedFields
{
    thread_id_t thread_id{};
    uintptr_t instruction_pointer{};
    uintptr_t data_pointer{};
    frame_id_t native_frame_id{};
    int code_firstlineno{};
};

template<typename RecordType>
class Registry
{
  public:
    using index_t = size_t;

    size_t size() const
    {
        return d_record_by_id.size();
    }

    std::pair<index_t, bool> registerRecord(const RecordType& record)
    {
        auto [it, inserted] = d_id_by_record.emplace(record, d_record_by_id.size());
        if (inserted) {
            d_record_by_id.push_back(record);
        }
        return std::make_pair(it->second, inserted);
    }

    RecordType& getRecord(index_t index)
    {
        return d_record_by_id[index];
    }

    const RecordType& getRecord(index_t index) const
    {
        return d_record_by_id[index];
    }

  private:
    std::unordered_map<RecordType, index_t, typename RecordType::Hash> d_id_by_record{};
    std::vector<RecordType> d_record_by_id{};
};

struct ThreadRecord
{
    const char* name;
};

struct ObjectRecord
{
    uintptr_t address;  // Address of the PyObject*
    bool is_created;  // true for creation, false for destruction
    frame_id_t native_frame_id{0};  // Optional native frame id for backtraces
};

}  // namespace memray::tracking_api
