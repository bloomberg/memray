#pragma once

#include <fstream>
#include <stddef.h>
#include <string>
#include <unordered_map>
#include <utility>

#include "Python.h"

#include "hooks.h"
#include "python_helpers.h"

namespace pensieve::tracking_api {

using frame_id_t = size_t;
using thread_id_t = unsigned long;

enum class RecordType {
    ALLOCATION = 1,
    FRAME_INDEX = 2,
    FRAME = 3,
    NATIVE_TRACE_INDEX = 4,
    MEMORY_MAP_START = 5,
    SEGMENT_HEADER = 6,
    SEGMENT = 7,
};

struct TrackerStats
{
    size_t n_allocations{0};
    size_t n_frames{0};
};

struct HeaderRecord
{
    int version{};
    TrackerStats stats{};
};

struct AllocationRecord
{
    thread_id_t tid;
    uintptr_t address;
    size_t size;
    hooks::Allocator allocator;
    int py_lineno;
    frame_id_t native_frame_id{0};
};

struct Allocation
{
    tracking_api::AllocationRecord record;
    size_t frame_index{0};
    size_t native_frame_index{0};
    size_t native_segment_generation{0};
    size_t n_allocactions{1};

    PyObject* toPythonObject() const;
};

enum FrameAction { PUSH, POP };

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
    int parent_lineno;

    auto operator==(const RawFrame& other) const -> bool
    {
        return (function_name == other.function_name && filename == other.filename
                && parent_lineno == other.parent_lineno);
    }

    struct Hash
    {
        auto operator()(pensieve::tracking_api::RawFrame const& frame) const noexcept -> std::size_t
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
            auto parent_lineno = std::hash<int>{}(frame.parent_lineno);
            return the_func ^ the_filename ^ parent_lineno;
        }
    };
};

struct Frame
{
    std::string function_name;
    std::string filename;
    int parent_lineno{0};
    int lineno{0};

    PyObject* toPythonObject(python_helpers::PyUnicode_Cache& pystring_cache, int the_lineno) const;

    auto operator==(const Frame& other) const -> bool
    {
        return (function_name == other.function_name && filename == other.filename
                && parent_lineno == other.parent_lineno && lineno == other.lineno);
    }

    struct Hash
    {
        auto operator()(pensieve::tracking_api::Frame const& frame) const noexcept -> std::size_t
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
            auto parent_lineno = std::hash<int>{}(frame.parent_lineno);
            auto lineno = std::hash<int>{}(frame.lineno);
            return the_func ^ the_filename ^ parent_lineno ^ lineno;
        }
    };
};

struct FrameSeqEntry
{
    frame_id_t frame_id;
    thread_id_t tid;
    FrameAction action;
};

struct UnresolvedNativeFrame
{
    uintptr_t ip;
    uint32_t index;
};

template<typename FrameType>
class FrameCollection
{
  public:
    explicit FrameCollection(frame_id_t starting_index = 0)
    : d_current_frame_id{starting_index} {};
    template<typename T>
    auto getIndex(T&& frame) -> std::pair<frame_id_t, bool>
    {
        auto it = d_frame_map.find(frame);
        if (it == d_frame_map.end()) {
            frame_id_t frame_id =
                    d_frame_map.emplace(std::forward<T>(frame), d_current_frame_id++).first->second;
            return std::make_pair(frame_id, true);
        }
        return std::make_pair(it->second, false);
    }

  private:
    frame_id_t d_current_frame_id{0};
    std::unordered_map<FrameType, frame_id_t, typename FrameType::Hash> d_frame_map{};
};

using pyframe_map_val_t = std::pair<frame_id_t, Frame>;
using pyframe_map_t = std::unordered_map<pyframe_map_val_t::first_type, pyframe_map_val_t::second_type>;

}  // namespace pensieve::tracking_api
