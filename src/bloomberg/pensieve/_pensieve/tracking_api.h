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
#include "record_writer.h"
#include "records.h"

namespace pensieve::api {
void
attach_init();

void
attach_fini();
}  // namespace pensieve::api

namespace pensieve::tracking_api {

// Trace function interface

/**
 * Trace function to be installed in all Python treads to track function calls
 *
 * This trace function's sole purpose is to give a thread-safe, GIL-synchronized view of the Python
 * stack. To retrieve the Python stack using the C-API forces the caller to have the GIL held. Requiring
 * the GIL in the allocator function has too much impact on performance and can deadlock extension
 *modules that have native locks that are not synchronized themselves with the GIL. For this reason we
 *need a way to record and store the Python call frame information in a way that we can read without the
 *need to use the C-API. This trace function maintains and does the bookeeping to mirror the Python stack
 *in a per-thread data structure that has the required properties and that can be accessed from the
 *allocator functions.
 *
 **/
int
PyTraceFunction(PyObject* obj, PyFrameObject* frame, int what, PyObject* arg);

/**
 * Installs the trace function in the current thread.
 *
 * This function installs the trace function in the current thread using the C-API. Before the
 * installation itself, this function will also pre-populate the data structure mirroring the Python
 * stack so all elements of Python stack that exist before the call to this function are also accounted
 * for.
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
    Tracker(Tracker& other) = delete;
    void operator=(const Tracker&) = delete;

    // Interface to get the tracker instance
    static Tracker* getTracker();

    // Allocation tracking interface
    void trackAllocation(void* ptr, size_t size, const char* func);
    void trackDeallocation(void* ptr, const char* func);
    static void invalidate_module_cache();

    // Frame stack interface
    static const std::vector<PyFrameRecord>& frameStack();
    static void initializeFrameStack();
    static void addFrame(const PyFrameRecord&& frame);
    static void popFrame();

    // Interface to activate/deactivate the tracking
    const std::atomic<bool>& isActive() const;
    void activate();
    void deactivate();

    // Allocation records API
    const std::vector<AllocationRecord>& getAllocationRecords();
    void clearAllocationRecords();

    api::InMemorySerializer& getSerializer();
    api::RecordWriter& getRecordWriter();

  private:
    // Constructors
    Tracker();

    // Data members
    static thread_local std::vector<PyFrameRecord> d_frame_stack;

    std::atomic<bool> d_active{false};
    static Tracker* d_instance;
    api::InMemorySerializer d_serializer;
    api::RecordWriter d_record_writer;

    // The only function that is allowed to instantiate the Tracker;
    friend void pensieve::api::attach_init();
};

}  // namespace pensieve::tracking_api
