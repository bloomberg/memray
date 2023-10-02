#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <memory>
#include <string>
#include <tuple>
#include <unistd.h>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include <cxxabi.h>

#include <libbacktrace/backtrace.h>
#include <libbacktrace/internal.h>

#include "python_helpers.h"
#include "records.h"

namespace memray::native_resolver {

static constexpr int PREALLOCATED_BACKTRACE_STATES = 64;
static constexpr int PREALLOCATED_IPS_CACHE_ITEMS = 32768;

class InternedString
{
  public:
    explicit InternedString(const std::string& orig);
    const std::string& get() const;
    operator const std::string&() const;

  private:
    static std::reference_wrapper<const std::string> internString(const std::string& orig);

    std::reference_wrapper<const std::string> d_ref;

    static std::mutex s_mutex;
    static std::unordered_set<std::string> s_interned_data;
};

class MemorySegment
{
  public:
    // Aliases and helpers
    struct Frame
    {
        std::string symbol;
        std::string filename;
        int lineno;
    };

    using ExpandedFrame = std::vector<Frame>;

    // Constructors
    MemorySegment(InternedString filename, uintptr_t start, uintptr_t end, backtrace_state* state);

    ExpandedFrame resolveIp(uintptr_t address) const;
    bool operator<(const MemorySegment& segment) const;
    bool operator!=(const MemorySegment& segment) const;
    bool isAddressInRange(uintptr_t addr) const;

    // Getters
    uintptr_t start() const;
    uintptr_t end() const;
    InternedString filename() const;

  private:
    // Methods
    void resolveFromDebugInfo(uintptr_t address, ExpandedFrame& expanded_frame) const;
    void resolveFromSymbolTable(uintptr_t address, ExpandedFrame& expanded_frame) const;

    // Data members
    InternedString d_filename;
    uintptr_t d_start;
    uintptr_t d_end;
    backtrace_state* d_state;
};

class ResolvedFrame
{
  public:
    // Constructors
    ResolvedFrame(InternedString symbol, InternedString filename, int lineno);

    // Methods
    PyObject* toPythonObject(python_helpers::PyUnicode_Cache& pystring_cache) const;

    // Getters
    const std::string& Symbol() const;
    const std::string& File() const;
    int Line() const;

  private:
    // Data members
    InternedString d_symbol;
    InternedString d_filename;
    int d_line;
};

class ResolvedFrames
{
  public:
    // Constructors
    template<typename T>
    ResolvedFrames(InternedString interned_memory_map_name, T&& frames)
    : d_interned_memory_map_name(interned_memory_map_name)
    , d_frames(std::forward<T>(frames))
    {
    }

    // Getters
    const std::string& memoryMap() const;
    const std::vector<ResolvedFrame>& frames() const;

  private:
    // Data members
    InternedString d_interned_memory_map_name;
    std::vector<ResolvedFrame> d_frames{};
};

class SymbolResolver
{
  public:
    using resolved_frames_t = std::shared_ptr<const ResolvedFrames>;

    // Constructors
    SymbolResolver();

    // Methods
    resolved_frames_t resolve(uintptr_t ip, size_t generation);
    void addSegments(
            const std::string& filename,
            uintptr_t addr,
            const std::vector<tracking_api::Segment>& segments);
    void clearSegments();

    static backtrace_state* getBacktraceState(InternedString filename, uintptr_t address_start);

    // Getters
    size_t currentSegmentGeneration() const;

  private:
    // Aliases and helpers
    using ips_cache_pair_t = std::pair<uintptr_t, ssize_t>;

    struct pair_hash
    {
        template<class T1, class T2>
        std::size_t operator()(const std::pair<T1, T2>& pair) const
        {
            return std::hash<T1>()(pair.first) ^ std::hash<T2>()(pair.second);
        }
    };

    using BacktraceStateCache =
            std::unordered_map<std::pair<const char*, uintptr_t>, backtrace_state*, pair_hash>;

    // Methods
    void addSegment(
            InternedString filename,
            backtrace_state* backtrace_state,
            uintptr_t address_start,
            uintptr_t address_end);
    std::vector<MemorySegment>& currentSegments();
    resolved_frames_t resolveFromSegments(uintptr_t ip, size_t generation);

    // Data members
    std::unordered_map<size_t, std::vector<MemorySegment>> d_segments;
    bool d_are_segments_dirty = false;
    mutable std::unordered_map<ips_cache_pair_t, resolved_frames_t, pair_hash> d_resolved_ips_cache;

    static std::mutex s_backtrace_states_mutex;
    static BacktraceStateCache s_backtrace_states;
};

std::vector<std::string>
unwindHere();
}  // namespace memray::native_resolver
