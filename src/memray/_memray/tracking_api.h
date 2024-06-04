#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <fstream>
#include <iterator>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <unordered_set>

#include <unwind.h>

#include "frameobject.h"

#if defined(__linux__)
#    define UNW_LOCAL_ONLY
#    include <libunwind.h>
#elif defined(__APPLE__)
#    include <execinfo.h>
#endif

#include "frame_tree.h"
#include "hooks.h"
#include "linker_shenanigans.h"
#include "record_writer.h"
#include "records.h"

#if defined(USE_MEMRAY_TLS_MODEL)
#    if defined(__GLIBC__)
#        define MEMRAY_FAST_TLS __attribute__((tls_model("initial-exec")))
#    else
#        define MEMRAY_FAST_TLS __attribute__((tls_model("local-dynamic")))
#    endif
#else
#    define MEMRAY_FAST_TLS
#endif

namespace memray::tracking_api {

struct RecursionGuard
{
    RecursionGuard()
    : wasLocked(isActive)
    {
        isActive = true;
    }

    ~RecursionGuard()
    {
        isActive = wasLocked;
    }

    const bool wasLocked;
    MEMRAY_FAST_TLS static thread_local bool isActive;
};

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
 * Trampoline that serves as the initial profiling function for each thread.
 *
 * This performs some one-time setup, then installs PyTraceFunction.
 */
int
PyTraceTrampoline(PyObject* obj, PyFrameObject* frame, int what, PyObject* arg);

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

    NativeTrace(std::vector<ip_t>& data)
    : d_data(data)
    {
    }

    auto begin() const
    {
        return std::reverse_iterator(d_data.begin() + d_skip + d_size);
    }
    auto end() const
    {
        return std::reverse_iterator(d_data.begin() + d_skip);
    }
    ip_t operator[](size_t i) const
    {
        return d_data[d_skip + d_size - 1 - i];
    }
    int size() const
    {
        return d_size;
    }
    __attribute__((always_inline)) inline bool fill(size_t skip)
    {
        size_t size;
        while (true) {
#ifdef __linux__
            size = unw_backtrace((void**)d_data.data(), d_data.size());
#elif defined(__APPLE__)
            size = ::backtrace((void**)d_data.data(), d_data.size());
#else
            return 0;
#endif
            if (size < d_data.size()) {
                break;
            }

            d_data.resize(d_data.size() * 2);
        }
        d_size = size > skip ? size - skip : 0;
        d_skip = skip;
        return d_size > 0;
    }

    static void setup()
    {
#ifdef __linux__
        // configure libunwind for better speed
        if (unw_set_caching_policy(unw_local_addr_space, UNW_CACHE_PER_THREAD)) {
            fprintf(stderr, "WARNING: Failed to enable per-thread libunwind caching.\n");
        }
#    if (UNW_VERSION_MAJOR > 1 && UNW_VERSION_MINOR >= 3)
        if (unw_set_cache_size(unw_local_addr_space, 1024, 0)) {
            fprintf(stderr, "WARNING: Failed to set libunwind cache size.\n");
        }
#    endif
#else
        return;
#endif
    }

    static inline void flushCache()
    {
#ifdef __linux__
        unw_flush_cache(unw_local_addr_space, 0, 0);
#else
        return;
#endif
    }

  private:
    size_t d_size = 0;
    size_t d_skip = 0;
    std::vector<ip_t>& d_data;
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
    ~Tracker();

    Tracker(Tracker& other) = delete;
    Tracker(Tracker&& other) = delete;
    void operator=(const Tracker&) = delete;
    void operator=(Tracker&&) = delete;

    // Interface to get the tracker instance
    static PyObject* createTracker(
            std::unique_ptr<RecordWriter> record_writer,
            bool native_traces,
            unsigned int memory_interval,
            bool follow_fork,
            bool trace_python_allocators);
    static PyObject* destroyTracker();
    static Tracker* getTracker();

    // Allocation tracking interface
    __attribute__((always_inline)) inline static void
    trackAllocation(void* ptr, size_t size, hooks::Allocator func)
    {
        if (RecursionGuard::isActive || !Tracker::isActive()) {
            return;
        }
        RecursionGuard guard;

        std::optional<NativeTrace> trace{std::nullopt};
        if (Tracker::areNativeTracesEnabled()) {
            if (!prepareNativeTrace(trace)) {
                return;
            }
            // Skip the internal frames so we don't need to filter them later.
            trace.value().fill(1);
        }

        std::unique_lock<std::mutex> lock(*s_mutex);
        Tracker* tracker = getTracker();
        if (tracker) {
            tracker->trackAllocationImpl(ptr, size, func, trace);
        }
    }

    static inline bool prepareNativeTrace(std::optional<NativeTrace>& trace)
    {
        auto t_trace_data_ptr = static_cast<std::vector<NativeTrace::ip_t>*>(
                pthread_getspecific(s_native_unwind_vector_key));
        if (!t_trace_data_ptr) {
            t_trace_data_ptr = new std::vector<NativeTrace::ip_t>();
            if (pthread_setspecific(s_native_unwind_vector_key, t_trace_data_ptr) != 0) {
                Tracker::deactivate();
                std::cerr << "memray: pthread_setspecific failed" << std::endl;
                delete t_trace_data_ptr;
                return false;
            }
            t_trace_data_ptr->resize(128);
        }
        trace.emplace(*t_trace_data_ptr);
        return true;
    }

    __attribute__((always_inline)) inline static void
    trackDeallocation(void* ptr, size_t size, hooks::Allocator func)
    {
        if (RecursionGuard::isActive || !Tracker::isActive()) {
            return;
        }
        RecursionGuard guard;

        std::unique_lock<std::mutex> lock(*s_mutex);
        Tracker* tracker = getTracker();
        if (tracker) {
            tracker->trackDeallocationImpl(ptr, size, func);
        }
    }

    __attribute__((always_inline)) inline static void invalidate_module_cache()
    {
        if (RecursionGuard::isActive || !Tracker::isActive()) {
            return;
        }
        RecursionGuard guard;

        std::unique_lock<std::mutex> lock(*s_mutex);
        Tracker* tracker = getTracker();
        if (tracker) {
            tracker->invalidate_module_cache_impl();
        }
    }

    __attribute__((always_inline)) inline static void registerThreadName(const char* name)
    {
        if (RecursionGuard::isActive || !Tracker::isActive()) {
            return;
        }
        RecursionGuard guard;

        std::unique_lock<std::mutex> lock(*s_mutex);
        Tracker* tracker = getTracker();
        if (tracker) {
            tracker->registerThreadNameImpl(name);
        }
    }

    inline static void registerThreadNameById(uint64_t thread, const char* name)
    {
        if (RecursionGuard::isActive || !Tracker::isActive()) {
            return;
        }
        RecursionGuard guard;

        std::unique_lock<std::mutex> lock(*s_mutex);
        Tracker* tracker = getTracker();
        if (tracker) {
            if (thread == (uint64_t)(pthread_self())) {
                tracker->registerThreadNameImpl(name);
            } else {
                // We've got a different thread's name, but don't know what id
                // has been assigned to that thread (if any!). Set this update
                // aside to be handled later, from that thread.
                tracker->d_cached_thread_names.emplace(thread, name);
            }
        }
    }

    // RawFrame stack interface
    bool pushFrame(const RawFrame& frame);
    bool popFrames(uint32_t count);

    // Interface to activate/deactivate the tracking
    static bool isActive();
    static void activate();
    static void deactivate();

    /**
     * Drop any references to frames on this thread's stack.
     *
     * This should be called when either the thread is dying or our profile
     * function is being uninstalled from it.
     */
    static void forgetPythonStack();

    /**
     * Sets a flag to enable integration with the `greenlet` module.
     */
    static void beginTrackingGreenlets();

    /**
     * Handle a notification of control switching from one greenlet to another.
     */
    static void handleGreenletSwitch(PyObject* from, PyObject* to);

    static void prepareFork();
    static void parentFork();
    static void childFork();

  private:
    class BackgroundThread
    {
      public:
        // Constructors
        BackgroundThread(std::shared_ptr<RecordWriter> record_writer, unsigned int memory_interval);

        // Methods
        void start();
        void stop();

      private:
        // Data members
        std::shared_ptr<RecordWriter> d_writer;
        bool d_stop{false};
        unsigned int d_memory_interval;
        std::mutex d_mutex;
        std::condition_variable d_cv;
        std::thread d_thread;
        mutable std::ifstream d_procs_statm;

        // Methods
        size_t getRSS() const;
        static unsigned long int timeElapsed();
        bool captureMemorySnapshot();
    };

    // Data members
    static std::unique_ptr<std::mutex> s_mutex;
    static pthread_key_t s_native_unwind_vector_key;
    static std::unique_ptr<Tracker> s_instance_owner;
    static std::atomic<Tracker*> s_instance;

    FrameCollection<RawFrame> d_frames;
    std::shared_ptr<RecordWriter> d_writer;
    FrameTree d_native_trace_tree;
    const bool d_unwind_native_frames;
    const unsigned int d_memory_interval;
    const bool d_follow_fork;
    const bool d_trace_python_allocators;
    linker::SymbolPatcher d_patcher;
    std::unique_ptr<BackgroundThread> d_background_thread;
    std::unordered_map<uint64_t, std::string> d_cached_thread_names;

    // Methods
    static size_t computeMainTidSkip();
    frame_id_t registerFrame(const RawFrame& frame);

    void trackAllocationImpl(
            void* ptr,
            size_t size,
            hooks::Allocator func,
            const std::optional<NativeTrace>& trace);
    void trackDeallocationImpl(void* ptr, size_t size, hooks::Allocator func);
    void invalidate_module_cache_impl();
    void updateModuleCacheImpl();
    void registerThreadNameImpl(const char* name);
    void registerCachedThreadName();
    void dropCachedThreadName();
    void registerPymallocHooks() const noexcept;
    void unregisterPymallocHooks() const noexcept;

    explicit Tracker(
            std::unique_ptr<RecordWriter> record_writer,
            bool native_traces,
            unsigned int memory_interval,
            bool follow_fork,
            bool trace_python_allocators);

    static bool areNativeTracesEnabled();
};

}  // namespace memray::tracking_api
