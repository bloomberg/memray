#pragma once

#include <algorithm>
#include <memory>
#include <string>
#include <tuple>
#include <unistd.h>
#include <unordered_map>
#include <utility>
#include <vector>

#include "Python.h"
#include <cxxabi.h>

#include <libbacktrace/backtrace.h>
#include <libbacktrace/internal.h>

#include "python_helpers.h"
#include "records.h"

namespace pensieve::native_resolver {

class StringStorage
{
  public:
    StringStorage();
    StringStorage(StringStorage& other) = delete;
    StringStorage(StringStorage&& other) = delete;
    void operator=(const StringStorage&) = delete;
    void operator=(StringStorage&&) = delete;
    size_t internString(const std::string& str, const char** interned_string = nullptr);
    const std::string& resolveString(size_t index) const;

  private:
    std::unordered_map<std::string, size_t> d_interned_data;
    std::vector<const std::string*> d_interned_data_storage;
};

class MemorySegment
{
  public:
    struct Frame
    {
        std::string symbol;
        std::string filename;
        int lineno;
    };

    using ExpandedFrame = std::vector<Frame>;

    MemorySegment(
            std::string filename,
            uintptr_t start,
            uintptr_t end,
            backtrace_state* state,
            size_t filename_index);
    ExpandedFrame resolveIp(uintptr_t address) const;
    bool operator<(const MemorySegment& segment) const;
    bool operator!=(const MemorySegment& segment) const;
    bool isAddressInRange(uintptr_t addr) const;

    uintptr_t start() const;
    uintptr_t end() const;
    size_t filenameIndex() const;
    const std::string& filename() const;

  private:
    void resolveFromDebugInfo(uintptr_t address, ExpandedFrame& expanded_frame) const;
    void resolveFromSymbolTable(uintptr_t address, ExpandedFrame& expanded_frame) const;

    std::string d_filename;
    uintptr_t d_start;
    uintptr_t d_end;
    size_t d_index;
    backtrace_state* d_state;
};

class ResolvedFrame
{
  public:
    ResolvedFrame(const MemorySegment::Frame& frame, std::shared_ptr<StringStorage> string_storage);
    const std::string& Symbol() const;
    const std::string& File() const;
    int Line() const;

    PyObject* toPythonObject(python_helpers::PyUnicode_Cache& pystring_cache) const;

  private:
    std::shared_ptr<StringStorage> d_string_storage;
    size_t d_symbol_index;
    size_t d_file_index;
    int d_line;
};

class ResolvedFrames
{
  public:
    template<typename T>
    ResolvedFrames(size_t memory_map_index, T&& frames, std::shared_ptr<StringStorage> strings_storage)
    : d_memory_map_index(memory_map_index)
    , d_frames(std::forward<T>(frames))
    , d_string_storage(std::move(strings_storage))
    {
    }

    const std::string& memoryMap() const;
    const std::vector<ResolvedFrame>& frames() const;

  private:
    size_t d_memory_map_index{0};
    std::vector<ResolvedFrame> d_frames{};
    std::shared_ptr<StringStorage> d_string_storage{nullptr};
};

class SymbolResolver
{
  public:
    using resolved_frames_t = std::shared_ptr<const ResolvedFrames>;

    SymbolResolver();
    resolved_frames_t resolve(uintptr_t ip, size_t generation);
    void addSegments(
            const std::string& filename,
            uintptr_t addr,
            const std::vector<tracking_api::Segment>& segments);
    void clearSegments();
    backtrace_state* findBacktraceState(const char* fileName, uintptr_t addressStart);
    size_t currentSegmentGeneration() const;

  private:
    resolved_frames_t resolveFromSegments(uintptr_t ip, size_t generation);
    std::unordered_map<size_t, std::vector<MemorySegment>> d_segments;
    ssize_t d_current_segment_generation{-1};
    bool d_are_segments_dirty = false;
    std::unordered_map<std::string, backtrace_state*> d_backtrace_states;
    std::unordered_map<uintptr_t, size_t> d_found_ips;
    std::shared_ptr<StringStorage> d_string_storage{std::make_shared<StringStorage>()};

    using ips_cache_pair_t = std::pair<uintptr_t, ssize_t>;
    struct ips_cache_pair_hash
    {
        template<class T1, class T2>
        std::size_t operator()(const std::pair<T1, T2>& pair) const
        {
            return std::hash<T1>()(pair.first) ^ std::hash<T2>()(pair.second);
        }
    };
    mutable std::unordered_map<ips_cache_pair_t, resolved_frames_t, ips_cache_pair_hash>
            d_resolved_ips_cache;

    void addSegment(
            const std::string& fileName,
            backtrace_state* backtraceState,
            size_t filename_index,
            uintptr_t address_start,
            uintptr_t address_end);
    std::vector<MemorySegment>& currentSegments();
};
}  // namespace pensieve::native_resolver
