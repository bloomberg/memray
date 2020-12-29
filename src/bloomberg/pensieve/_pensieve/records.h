#pragma once

#include <algorithm>
#include <fstream>
#include <functional>
#include <iostream>
#include <ostream>
#include <pthread.h>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "Python.h"

#include <hooks.h>

namespace pensieve::tracking_api {

using frame_id_t = size_t;
using thread_id_t = unsigned long;

enum class RecordType {
    ALLOCATION = 1,
    FRAME_INDEX = 2,
    FRAME = 3,
};

struct AllocationRecord
{
    thread_id_t tid;
    unsigned long address;
    size_t size;
    hooks::Allocator allocator;
};

enum FrameAction { PUSH, POP };

struct RawFrame
{
    const char* function_name;
    const char* filename;
    unsigned long lineno;

    auto operator==(const RawFrame& other) const -> bool
    {
        return (function_name == other.function_name && filename == other.filename
                && lineno == other.lineno);
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
            auto the_lineno = std::hash<unsigned long>{}(frame.lineno);
            return the_func ^ the_filename ^ the_lineno;
        }
    };
};

struct Frame
{
    std::string function_name;
    std::string filename;
    unsigned long lineno;
};

struct FrameSeqEntry
{
    frame_id_t frame_id;
    thread_id_t tid;
    FrameAction action;
};

class FrameCollection
{
  public:
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
    std::unordered_map<RawFrame, frame_id_t, RawFrame::Hash> d_frame_map{};
};

using pyframe_map_val_t = std::pair<frame_id_t, Frame>;
using pyframe_map_t = std::unordered_map<pyframe_map_val_t::first_type, pyframe_map_val_t::second_type>;

}  // namespace pensieve::tracking_api
