#pragma once

#include <fstream>
#include <stddef.h>
#include <string>
#include <unordered_map>
#include <utility>

#include "Python.h"

#include "hooks.h"
#include "python_helpers.h"

namespace memray::tracking_api {

const char MAGIC[] = "memray";
const int CURRENT_HEADER_VERSION = 7;

using frame_id_t = size_t;
using thread_id_t = unsigned long;
using millis_t = long long;

enum class RecordType : unsigned char {
    UNINITIALIZED = 0,
    ALLOCATION = 1,
    ALLOCATION_WITH_NATIVE = 2,
    FRAME_INDEX = 3,
    FRAME_PUSH = 4,
    NATIVE_TRACE_INDEX = 5,
    MEMORY_MAP_START = 6,
    SEGMENT_HEADER = 7,
    SEGMENT = 8,
    FRAME_POP = 9,
    THREAD_RECORD = 10,
    MEMORY_RECORD = 11,
    CONTEXT_SWITCH = 12,
};

struct RecordTypeAndFlags
{
    RecordTypeAndFlags()
    : record_type(RecordType::UNINITIALIZED)
    , flags(0)
    {
    }

    RecordTypeAndFlags(RecordType record_type_, unsigned char flags_)
    : record_type(record_type_)
    , flags(flags_)
    {
        // Ensure both values fit into 4 bits
        assert(static_cast<int>(record_type_) == (static_cast<int>(record_type_) & 0x0f));
        assert(static_cast<int>(flags_) == (static_cast<int>(flags_) & 0x0f));
    }

    RecordType record_type : 4;
    unsigned char flags : 4;
};

static_assert(sizeof(RecordTypeAndFlags) == 1);

struct TrackerStats
{
    size_t n_allocations{0};
    size_t n_frames{0};
    millis_t start_time{};
    millis_t end_time{};
};

enum PythonAllocatorType {
    PYTHONALLOCATOR_PYMALLOC = 1,
    PYTHONALLOCATOR_PYMALLOC_DEBUG = 2,
    PYTHONALLOCATOR_MALLOC = 3,
    PYTHONALLOCATOR_OTHER = 4,
};

struct HeaderRecord
{
    char magic[sizeof(MAGIC)];
    int version{};
    bool native_traces{false};
    TrackerStats stats{};
    std::string command_line;
    int pid{-1};
    PythonAllocatorType python_allocator;
};

struct MemoryRecord
{
    unsigned long int ms_since_epoch;
    size_t rss;
};

struct AllocationRecord
{
    uintptr_t address;
    size_t size;
    hooks::Allocator allocator;
};

struct NativeAllocationRecord
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

struct RawFrame
{
    const char* function_name;
    const char* filename;
    int lineno;

    auto operator==(const RawFrame& other) const -> bool
    {
        return (function_name == other.function_name && filename == other.filename
                && lineno == other.lineno);
    }

    struct Hash
    {
        auto operator()(memray::tracking_api::RawFrame const& frame) const noexcept -> std::size_t
        {
            // Keep this hashing fast and simple as this has a non trivial
            // performance impact on the tracing functionality. We don't hash
            // the contents of the strings because the interpreter will give us
            // the same char* for the same code object. Of course, we can have
            // some scenarios where two functions with the same function name have
            // two different char* but in that case we will end registering the
            // name twice, which is a good compromise given the speed that we
            // gain keeping this simple.

            auto the_func = std::hash<const char*>{}(frame.function_name);
            auto the_filename = std::hash<const char*>{}(frame.filename);
            auto lineno = std::hash<int>{}(frame.lineno);
            return the_func ^ the_filename ^ lineno;
        }
    };
};

struct Frame
{
    std::string function_name;
    std::string filename;
    int lineno{0};

    PyObject* toPythonObject(python_helpers::PyUnicode_Cache& pystring_cache) const;

    auto operator==(const Frame& other) const -> bool
    {
        return (function_name == other.function_name && filename == other.filename
                && lineno == other.lineno);
    }

    struct Hash
    {
        auto operator()(memray::tracking_api::Frame const& frame) const noexcept -> std::size_t
        {
            // Keep this hashing fast and simple as this has a non trivial
            // performance impact on the tracing functionality. We don't hash
            // the contents of the strings because the interpreter will give us
            // the same char* for the same code object. Of course, we can have
            // some scenarios where two functions with the same function name have
            // two different char* but in that case we will end registering the
            // name twice, which is a good compromise given the speed that we
            // gain keeping this simple.

            auto the_func = std::hash<std::string>{}(frame.function_name);
            auto the_filename = std::hash<std::string>{}(frame.filename);
            auto lineno = std::hash<int>{}(frame.lineno);
            return the_func ^ the_filename ^ lineno;
        }
    };
};

struct FramePush
{
    frame_id_t frame_id;
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
    frame_id_t python_frame_id{};
    int python_line_number{};
};

template<typename FrameType>
class FrameCollection
{
  public:
    explicit FrameCollection(const frame_id_t& starting_index, const unsigned int& index_increment)
    : d_index_increment{index_increment}
    , d_current_frame_id{starting_index} {};

    template<typename T>
    auto getIndex(T&& frame) -> std::pair<frame_id_t, bool>
    {
        auto it = d_frame_map.find(frame);
        if (it == d_frame_map.end()) {
            frame_id_t frame_id =
                    d_frame_map.emplace(std::forward<T>(frame), d_current_frame_id).first->second;
            d_current_frame_id += d_index_increment;
            return std::make_pair(frame_id, true);
        }
        return std::make_pair(it->second, false);
    }

  private:
    const unsigned int d_index_increment;
    frame_id_t d_current_frame_id;
    std::unordered_map<FrameType, frame_id_t, typename FrameType::Hash> d_frame_map{};
};

using pyrawframe_map_val_t = std::pair<frame_id_t, RawFrame>;
using pyframe_map_val_t = std::pair<frame_id_t, Frame>;
using pyframe_map_t = std::unordered_map<pyframe_map_val_t::first_type, pyframe_map_val_t::second_type>;

struct ThreadRecord
{
    const char* name;
};

}  // namespace memray::tracking_api
