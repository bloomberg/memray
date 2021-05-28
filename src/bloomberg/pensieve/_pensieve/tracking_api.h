#pragma once

#include <atomic>
#include <cstddef>
#include <iterator>
#include <memory>
#include <string>
#include <unordered_set>

#include <unwind.h>

#include "frameobject.h"

#define UNW_LOCAL_ONLY
#include <libunwind.h>

#include "elf_shenanigans.h"
#include "frame_tree.h"
#include "hooks.h"
#include "record_writer.h"
#include "records.h"

namespace pensieve::tracking_api {

// Trace function interface

/**
 * Trace function to be installed in all Python treads to track function calls
 *
 * This trace function's sole purpose is to give a thread-safe, GIL-synchronized view of the Python
 * stack. To retrieve the Python stack using the C-API forces the caller to have the GIL held. Requiring
 * the GIL in the allocator function has too much impact on performance and can deadlock extension
 * modules that have native locks that are not synchronized themselves with the GIL. For this reason we
 * need a way to record and store the Python call frame information in a way that we can read without the
 * need to use the C-API. This trace function writes to disk the PUSH and POP operations so the Python
 *stack at any point can be reconstructed later.
 *
 **/
int
PyTraceFunction(PyObject* obj, PyFrameObject* frame, int what, PyObject* arg);

/**
 * Installs the trace function in the current thread.
 *
 * This function installs the trace function in the current thread using the C-API.
 *
 * */
void
install_trace_function();

class NativeTrace
{
  public:
    using ip_t = frame_id_t;

    auto begin() const
    {
        return std::reverse_iterator(d_data + d_skip + d_size);
    }
    auto end() const
    {
        return std::reverse_iterator(d_data + d_skip);
    }
    ip_t operator[](size_t i) const
    {
        return d_data[d_skip + d_size - 1 - i];
    }
    int size() const
    {
        return d_size;
    }
    bool fill(int skip)
    {
        int size = unwind(d_data);
        d_size = size > skip ? size - skip : 0;
        d_skip = skip;
        return d_size > 0;
    }
    static void setup()
    {
        // configure libunwind for better speed
        if (unw_set_caching_policy(unw_local_addr_space, UNW_CACHE_PER_THREAD)) {
            fprintf(stderr, "WARNING: Failed to enable per-thread libunwind caching.\n");
        }
        if (unw_set_cache_size(unw_local_addr_space, 1024, 0)) {
            fprintf(stderr, "WARNING: Failed to set libunwind cache size.\n");
        }
    }

    static inline void flushCache()
    {
        unw_flush_cache(unw_local_addr_space, 0, 0);
    }

  private:
    static const size_t MAX_SIZE = 64;
    static int unwind(frame_id_t* data)
    {
        return unw_backtrace((void**)data, MAX_SIZE);
    }

  private:
    int d_size = 0;
    int d_skip = 0;
    ip_t d_data[MAX_SIZE];
};

/**
 * Singleton managing all the global state and functionality of the tracing mechanism
 *
 * This class acts as the only interface to the tracing functionality and encapsulates all the
 * required global state. *All access* must be done through the singleton interface as the singleton
 * has the same lifetime of the entire program. The singleton can be activated and deactivated to
 * temporarily stop the tracking as desired. The singleton manages a mirror copy of the Python stack
 * so it can be accessed synchronized by its the allocation tracking interfaces.
 * */
class Tracker
{
  public:
    // Constructors
    explicit Tracker(const std::string& file_name, bool native_frames, const std::string& command_line);
    ~Tracker();

    Tracker(Tracker& other) = delete;
    Tracker(Tracker&& other) = delete;
    void operator=(const Tracker&) = delete;
    void operator=(Tracker&&) = delete;

    // Interface to get the tracker instance
    static Tracker* getTracker();

    // Allocation tracking interface
    void trackAllocation(void* ptr, size_t size, hooks::Allocator func);
    void trackDeallocation(void* ptr, size_t size, hooks::Allocator func);
    void invalidate_module_cache();
    void updateModuleCache();

    // RawFrame stack interface
    void pushFrame(const RawFrame& frame);
    void popFrame(const RawFrame& frame);

    // Interface to activate/deactivate the tracking
    static const std::atomic<bool>& isActive();
    static void activate();
    static void deactivate();

  private:
    // Data members
    FrameCollection<RawFrame> d_frames{};
    static std::atomic<bool> d_active;
    static std::atomic<Tracker*> d_instance;
    std::unique_ptr<RecordWriter> d_writer;
    FrameTree d_native_trace_tree;
    bool d_unwind_native_frames;
    elf::SymbolPatcher d_patcher;

    // Methods
    frame_id_t registerFrame(const RawFrame& frame);
};

}  // namespace pensieve::tracking_api
