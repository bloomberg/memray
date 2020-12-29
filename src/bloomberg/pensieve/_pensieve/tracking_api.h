#pragma once

#include <atomic>
#include <chrono>
#include <vector>

#include <memory>
#include <mutex>
#include <ostream>
#include <vector>

#include "Python.h"
#include "frameobject.h"
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
    explicit Tracker(const std::string& file_name);
    ~Tracker();

    Tracker(Tracker& other) = delete;
    Tracker(Tracker&& other) = delete;
    void operator=(const Tracker&) = delete;
    void operator=(Tracker&&) = delete;

    // Interface to get the tracker instance
    static Tracker* getTracker();

    // Allocation tracking interface
    void trackAllocation(void* ptr, size_t size, const hooks::Allocator func) const;
    void trackDeallocation(void* ptr, const hooks::Allocator func) const;
    static void invalidate_module_cache();

    // RawFrame stack interface
    void initializeFrameStack();
    void addFrame(const RawFrame& frame);
    void popFrame(const RawFrame& frame);

    // Interface to activate/deactivate the tracking
    const std::atomic<bool>& isActive() const;
    void activate();
    void deactivate();

  private:
    static frame_map_t d_frames;
    std::atomic<bool> d_active{false};
    static std::atomic<Tracker*> d_instance;
    std::unique_ptr<RecordWriter> d_writer;
};

}  // namespace pensieve::tracking_api
