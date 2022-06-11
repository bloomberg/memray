#include <cassert>
#include <limits.h>
#include <link.h>
#include <mutex>
#include <type_traits>
#include <unistd.h>
#include <utility>

#include <Python.h>

#include "exceptions.h"
#include "hooks.h"
#include "record_writer.h"
#include "records.h"
#include "tracking_api.h"

using namespace memray::exception;
using namespace std::chrono_literals;

namespace {

std::string
get_executable()
{
    char buff[PATH_MAX + 1];
    ssize_t len = ::readlink("/proc/self/exe", buff, sizeof(buff));
    if (len > PATH_MAX) {
        throw std::runtime_error("Path to executable is more than PATH_MAX bytes");
    } else if (len == -1) {
        throw std::runtime_error("Could not determine executable path");
    }
    return std::string(buff, len);
}

static bool
starts_with(const std::string& haystack, const std::string_view& needle)
{
    return haystack.compare(0, needle.size(), needle) == 0;
}

// Track how many times a new Tracker has been created
std::atomic<unsigned int> g_tracker_generation;

}  // namespace

namespace memray::tracking_api {

MEMRAY_FAST_TLS thread_local bool RecursionGuard::isActive = false;

static inline thread_id_t
thread_id()
{
    return reinterpret_cast<thread_id_t>(pthread_self());
};

// Tracker interface

// If a TLS variable has not been constructed, accessing it will cause it to be
// constructed. That's normally great, but we need to prevent that from
// happening unexpectedly for the TLS vector owned by this class.
//
// Methods of this class can be called during thread teardown. It's possible
// that, after the TLS vector for a dying thread has already been destroyed,
// libpthread makes a call to free() that calls into our Tracker, and if it
// does, we must prevent it touching the vector again and re-constructing it.
// Otherwise, it would be re-constructed immediately but its destructor would
// be added to this thread's list of finalizers after all the finalizers for
// the thread already ran.  If that happens, the vector will be free()d before
// its destructor runs. Worse, its destructor will remain on the list of
// finalizers for the current thread's pthread struct, and its destructor will
// later be run on that already free()d memory if this thread's pthread struct
// is ever reused. When that happens it tends to cause heap corruption, because
// another vector is placed at the same location as the original one, and the
// vector destructor runs twice on it (once for the newly created vector, and
// once for the vector that had been created before the thread died and the
// pthread struct was reused).
//
// To prevent that, we only create the vector in one method (pushPythonFrame).
// All other methods access a pointer called `d_stack` that is set to the TLS
// stack when it is created by pushPythonFrame, and set to a null pointer when
// the TLS stack is destroyed.
//
// This can result in this class being constructed during thread teardown, but
// that doesn't cause the same problem because it has a trivial destructor.
class PythonStackTracker
{
  private:
    struct LazilyEmittedFrame
    {
        PyFrameObject* frame;
        RawFrame raw_frame_record;
        bool emitted;
    };

  public:
    void reset(PyFrameObject* current_frame);
    void emitPendingPops();
    void emitPendingPushes();
    int getCurrentPythonLineNumber();
    void setMostRecentFrameLineNumber(int lineno);
    int pushPythonFrame(PyFrameObject* frame);
    void popPythonFrame();

  private:
    uint32_t d_num_pending_pops{};
    uint32_t d_tracker_generation{};
    std::vector<LazilyEmittedFrame>* d_stack{};
};

// See giant comment above.
static_assert(std::is_trivially_destructible<PythonStackTracker>::value);
MEMRAY_FAST_TLS thread_local PythonStackTracker t_python_stack_tracker;

void
PythonStackTracker::reset(PyFrameObject* current_frame)
{
    d_num_pending_pops = 0;
    if (d_stack) {
        d_stack->clear();
    }

    if (current_frame && 0 != pushPythonFrame(current_frame)) {
        PyErr_Clear();  // Nothing to be done about it here.
    }
}

inline void
PythonStackTracker::emitPendingPops()
{
    if (d_tracker_generation != g_tracker_generation) {
        // The Tracker has changed underneath us (either by an after-fork
        // handler, or by another thread destroying the Tracker we were using
        // and installing a new one). Either way, update our state to reflect
        // that nothing has been emitted to the (new) output file.
        d_tracker_generation = g_tracker_generation;
        d_num_pending_pops = 0;
        if (d_stack) {
            for (auto it = d_stack->begin(); it != d_stack->end(); it++) {
                it->emitted = false;
            }
        }
    } else {
        Tracker::getTracker()->popFrames(d_num_pending_pops);
        d_num_pending_pops = 0;
    }
}

void
PythonStackTracker::emitPendingPushes()
{
    if (!d_stack) {
        return;
    }

    auto last_emitted_rit =
            std::find_if(d_stack->rbegin(), d_stack->rend(), [](auto& f) { return f.emitted; });

    for (auto to_emit = last_emitted_rit.base(); to_emit != d_stack->end(); to_emit++) {
        if (!Tracker::getTracker()->pushFrame(to_emit->raw_frame_record)) {
            break;
        }
        to_emit->emitted = true;
    }
}

inline int
PythonStackTracker::getCurrentPythonLineNumber()
{
    if (d_stack && !d_stack->empty()) {
        return PyFrame_GetLineNumber(d_stack->back().frame);
    }
    return 0;
}

void
PythonStackTracker::setMostRecentFrameLineNumber(int lineno)
{
    if (!d_stack || d_stack->empty() || d_stack->back().raw_frame_record.lineno == lineno) {
        return;
    }

    d_stack->back().raw_frame_record.lineno = lineno;
    if (d_stack->back().emitted) {
        // If it was already emitted with an old line number, pop that frame
        // and re-emit it with the new line number.
        d_num_pending_pops += 1;
        d_stack->back().emitted = false;
    }
}

int
PythonStackTracker::pushPythonFrame(PyFrameObject* frame)
{
    const char* function = PyUnicode_AsUTF8(frame->f_code->co_name);
    if (function == nullptr) {
        return -1;
    }

    const char* filename = PyUnicode_AsUTF8(frame->f_code->co_filename);
    if (filename == nullptr) {
        return -1;
    }

    int parent_lineno = getCurrentPythonLineNumber();

    struct StackCreator
    {
        std::vector<LazilyEmittedFrame> stack;

        StackCreator()
        {
            const size_t INITIAL_PYTHON_STACK_FRAMES = 1024;
            stack.reserve(INITIAL_PYTHON_STACK_FRAMES);
            t_python_stack_tracker.d_stack = &stack;
        }
        ~StackCreator()
        {
            t_python_stack_tracker.d_stack = nullptr;
        }
    };

    setMostRecentFrameLineNumber(parent_lineno);
    MEMRAY_FAST_TLS static thread_local StackCreator t_stack_creator;
    t_stack_creator.stack.push_back({frame, {function, filename, 0}, false});
    assert(d_stack);  // The above call sets d_stack if it wasn't already set.
    return 0;
}

void
PythonStackTracker::popPythonFrame()
{
    if (d_stack && !d_stack->empty()) {
        if (d_stack->back().emitted) {
            d_num_pending_pops += 1;
            assert(d_num_pending_pops != 0);  // Ensure we didn't overflow.
        }
        d_stack->pop_back();

        if (d_stack->empty()) {
            // Every frame we've pushed has been popped. Emit pending pops now
            // in case the thread is exiting and we don't get another chance.
            emitPendingPops();
        }
    }
}

std::atomic<bool> Tracker::d_active = false;
std::unique_ptr<Tracker> Tracker::d_instance_owner;
std::atomic<Tracker*> Tracker::d_instance = nullptr;
MEMRAY_FAST_TLS thread_local size_t NativeTrace::MAX_SIZE{128};

Tracker::Tracker(
        std::unique_ptr<RecordWriter> record_writer,
        bool native_traces,
        unsigned int memory_interval,
        bool follow_fork,
        bool trace_python_allocators)
: d_writer(std::move(record_writer))
, d_unwind_native_frames(native_traces)
, d_memory_interval(memory_interval)
, d_follow_fork(follow_fork)
, d_trace_python_allocators(trace_python_allocators)
{
    g_tracker_generation++;

    // Note: this must be set before the hooks are installed.
    d_instance = this;

    static std::once_flag once;
    call_once(once, [] {
        hooks::ensureAllHooksAreValid();
        NativeTrace::setup();

        // We must do this last so that a child can't inherit an environment
        // where only half of our one-time setup is done.
        pthread_atfork(&prepareFork, &parentFork, &childFork);
    });

    if (!d_writer->writeHeader(false)) {
        throw IoError{"Failed to write output header"};
    }
    updateModuleCache();

    RecursionGuard guard;
    tracking_api::install_trace_function();  //  TODO pass our instance here to avoid static object
    if (d_trace_python_allocators) {
        registerPymallocHooks();
    }
    d_patcher.overwrite_symbols();

    d_background_thread = std::make_unique<BackgroundThread>(d_writer, memory_interval);
    d_background_thread->start();

    tracking_api::Tracker::activate();
}

Tracker::~Tracker()
{
    RecursionGuard guard;
    tracking_api::Tracker::deactivate();
    d_background_thread->stop();
    t_python_stack_tracker.reset(nullptr);
    d_patcher.restore_symbols();
    if (d_trace_python_allocators) {
        unregisterPymallocHooks();
    }
    d_writer->writeTrailer();
    d_writer->writeHeader(true);
    d_writer.reset();

    // Note: this must not be unset before the hooks are uninstalled.
    d_instance = nullptr;
}

Tracker::BackgroundThread::BackgroundThread(
        std::shared_ptr<RecordWriter> record_writer,
        unsigned int memory_interval)
: d_writer(std::move(record_writer))
, d_memory_interval(memory_interval)
{
    d_procs_statm.open("/proc/self/statm");
    if (!d_procs_statm) {
        throw IoError{"Failed to open /proc/self/statm"};
    }
}

unsigned long int
Tracker::BackgroundThread::timeElapsed()
{
    std::chrono::milliseconds ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch());
    return ms.count();
}

size_t
Tracker::BackgroundThread::getRSS() const
{
    static long pagesize = sysconf(_SC_PAGE_SIZE);
    constexpr int max_unsigned_long_chars = std::numeric_limits<unsigned long>::digits10 + 1;
    constexpr int bufsize = (max_unsigned_long_chars + sizeof(' ')) * 2;
    char buffer[bufsize];
    d_procs_statm.read(buffer, sizeof(buffer) - 1);
    buffer[d_procs_statm.gcount()] = '\0';
    d_procs_statm.clear();
    d_procs_statm.seekg(0);

    size_t rss;
    if (sscanf(buffer, "%*u %zu", &rss) != 1) {
        std::cerr << "WARNING: Failed to read RSS value from /proc/self/statm" << std::endl;
        d_procs_statm.close();
        return 0;
    }

    return rss * pagesize;
}

void
Tracker::BackgroundThread::start()
{
    assert(d_thread.get_id() == std::thread::id());
    d_thread = std::thread([&]() {
        RecursionGuard::isActive = true;
        while (true) {
            {
                std::unique_lock<std::mutex> lock(d_mutex);
                d_cv.wait_for(lock, d_memory_interval * 1ms, [this]() { return d_stop; });
                if (d_stop) {
                    break;
                }
            }
            size_t rss = getRSS();
            if (rss == 0) {
                Tracker::deactivate();
                break;
            }
            if (!d_writer->writeRecord(MemoryRecord{timeElapsed(), rss})) {
                std::cerr << "Failed to write output, deactivating tracking" << std::endl;
                Tracker::deactivate();
                break;
            }
        }
    });
}

void
Tracker::BackgroundThread::stop()
{
    {
        std::scoped_lock<std::mutex> lock(d_mutex);
        d_stop = true;
        d_cv.notify_one();
    }
    if (d_thread.joinable()) {
        try {
            d_thread.join();
        } catch (const std::system_error&) {
        }
    }
}

void
Tracker::prepareFork()
{
    // Don't do any custom track_allocation handling while inside fork
    RecursionGuard::isActive = true;
}

void
Tracker::parentFork()
{
    // We can continue tracking
    RecursionGuard::isActive = false;
}

void
Tracker::childFork()
{
    // Intentionally leak any old tracker. Its destructor cannot be called,
    // because it would try to destroy mutexes that might be locked by threads
    // that no longer exist, and to join a background thread that no longer
    // exists, and potentially to flush buffered output to a socket it no
    // longer owns. Note that d_instance_owner is always set after d_instance
    // and unset before d_instance.
    (void)d_instance_owner.release();

    Tracker* old_tracker = d_instance;

    // If we inherited an active tracker, try to clone its record writer.
    std::unique_ptr<RecordWriter> new_writer;
    if (old_tracker && old_tracker->isActive() && old_tracker->d_follow_fork) {
        new_writer = old_tracker->d_writer->cloneInChildProcess();
    }

    if (!new_writer) {
        // We either have no tracker, or a deactivated tracker, or a tracker
        // with a sink that can't be cloned. Unset our singleton and bail out.
        // Note that the old tracker's hooks may still be installed. This is
        // OK, as long as they always check the (static) isActive() flag before
        // calling any methods on the now null tracker singleton.
        d_instance = nullptr;
        RecursionGuard::isActive = false;
        return;
    }

    // Re-enable tracking with a brand new tracker.
    d_instance_owner.reset(new Tracker(
            std::move(new_writer),
            old_tracker->d_unwind_native_frames,
            old_tracker->d_memory_interval,
            old_tracker->d_follow_fork,
            old_tracker->d_trace_python_allocators));
    RecursionGuard::isActive = false;
}

void
Tracker::trackAllocationImpl(void* ptr, size_t size, hooks::Allocator func)
{
    if (RecursionGuard::isActive || !Tracker::isActive()) {
        return;
    }
    RecursionGuard guard;

    // Grab a reference to the TLS variable to guarantee it's only resolved once.
    auto& python_stack_tracker = t_python_stack_tracker;
    int lineno = python_stack_tracker.getCurrentPythonLineNumber();

    python_stack_tracker.setMostRecentFrameLineNumber(lineno);
    python_stack_tracker.emitPendingPops();
    python_stack_tracker.emitPendingPushes();

    if (d_unwind_native_frames) {
        NativeTrace trace;
        frame_id_t native_index = 0;
        // Skip the internal frames so we don't need to filter them later.
        if (trace.fill(2)) {
            native_index = d_native_trace_tree.getTraceIndex(trace, [&](frame_id_t ip, uint32_t index) {
                return d_writer->writeRecord(UnresolvedNativeFrame{ip, index});
            });
        }
        NativeAllocationRecord record{reinterpret_cast<uintptr_t>(ptr), size, func, native_index};
        if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
            std::cerr << "Failed to write output, deactivating tracking" << std::endl;
            deactivate();
        }

    } else {
        AllocationRecord record{reinterpret_cast<uintptr_t>(ptr), size, func};
        if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
            std::cerr << "Failed to write output, deactivating tracking" << std::endl;
            deactivate();
        }
    }
}

void
Tracker::trackDeallocationImpl(void* ptr, size_t size, hooks::Allocator func)
{
    if (RecursionGuard::isActive || !Tracker::isActive()) {
        return;
    }
    RecursionGuard guard;

    AllocationRecord record{reinterpret_cast<uintptr_t>(ptr), size, func};
    if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
        std::cerr << "Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::invalidate_module_cache_impl()
{
    RecursionGuard guard;
    d_patcher.overwrite_symbols();
    updateModuleCache();
}

static int
dl_iterate_phdr_callback(struct dl_phdr_info* info, [[maybe_unused]] size_t size, void* data)
{
    auto writer = reinterpret_cast<RecordWriter*>(data);
    const char* filename = info->dlpi_name;
    std::string executable;
    assert(filename != nullptr);
    if (!filename[0]) {
        executable = get_executable();
        filename = executable.c_str();
    }
    if (::starts_with(filename, "linux-vdso.so")) {
        // This cannot be resolved to anything, so don't write it to the file
        return 0;
    }

    std::vector<Segment> segments;
    for (int i = 0; i < info->dlpi_phnum; i++) {
        const auto& phdr = info->dlpi_phdr[i];
        if (phdr.p_type == PT_LOAD) {
            segments.emplace_back(Segment{phdr.p_vaddr, phdr.p_memsz});
        }
    }

    if (!writer->writeRecordUnsafe(SegmentHeader{filename, segments.size(), info->dlpi_addr})) {
        std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
        Tracker::deactivate();
        return 1;
    }

    for (const auto& segment : segments) {
        if (!writer->writeRecordUnsafe(segment)) {
            std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
            Tracker::deactivate();
            return 1;
        }
    }

    return 0;
}

void
Tracker::updateModuleCacheImpl()
{
    if (!d_unwind_native_frames) {
        return;
    }
    auto writer_lock = d_writer->acquireLock();
    if (!d_writer->writeRecordUnsafe(MemoryMapStart{})) {
        std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }

    dl_iterate_phdr(&dl_iterate_phdr_callback, d_writer.get());
}

void
Tracker::registerThreadNameImpl(const char* name)
{
    if (!d_writer->writeThreadSpecificRecord(thread_id(), ThreadRecord{name})) {
        std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

frame_id_t
Tracker::registerFrame(const RawFrame& frame)
{
    const auto [frame_id, is_new_frame] = d_frames.getIndex(frame);
    if (is_new_frame) {
        pyrawframe_map_val_t frame_index{frame_id, frame};
        if (!d_writer->writeRecord(frame_index)) {
            std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
            deactivate();
        }
    }
    return frame_id;
}

bool
Tracker::popFrames(uint32_t count)
{
    const FramePop entry{count};
    if (!d_writer->writeThreadSpecificRecord(thread_id(), entry)) {
        std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
        return false;
    }
    return true;
}

bool
Tracker::pushFrame(const RawFrame& frame)
{
    const frame_id_t frame_id = registerFrame(frame);
    const FramePush entry{frame_id};
    if (!d_writer->writeThreadSpecificRecord(thread_id(), entry)) {
        std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
        return false;
    }
    return true;
}

void
Tracker::activate()
{
    d_active = true;
}

void
Tracker::deactivate()
{
    d_active = false;
}

const std::atomic<bool>&
Tracker::isActive()
{
    return Tracker::d_active;
}

// Static methods managing the singleton

PyObject*
Tracker::createTracker(
        std::unique_ptr<RecordWriter> record_writer,
        bool native_traces,
        unsigned int memory_interval,
        bool follow_fork,
        bool trace_python_allocators)
{
    // Note: the GIL is used for synchronization of the singleton
    d_instance_owner.reset(new Tracker(
            std::move(record_writer),
            native_traces,
            memory_interval,
            follow_fork,
            trace_python_allocators));
    Py_RETURN_NONE;
}

PyObject*
Tracker::destroyTracker()
{
    // Note: the GIL is used for synchronization of the singleton
    d_instance_owner.reset();
    Py_RETURN_NONE;
}

Tracker*
Tracker::getTracker()
{
    return d_instance;
}

static struct
{
    PyMemAllocatorEx raw;
    PyMemAllocatorEx mem;
    PyMemAllocatorEx obj;
} s_orig_pymalloc_allocators;

void
Tracker::registerPymallocHooks() const noexcept
{
    assert(d_trace_python_allocators);
    PyMemAllocatorEx alloc;

    PyMem_GetAllocator(PYMEM_DOMAIN_RAW, &alloc);
    if (alloc.free == &intercept::pymalloc_free) {
        // Nothing to do; our hooks are already installed.
        return;
    }

    alloc.malloc = intercept::pymalloc_malloc;
    alloc.calloc = intercept::pymalloc_calloc;
    alloc.realloc = intercept::pymalloc_realloc;
    alloc.free = intercept::pymalloc_free;
    PyMem_GetAllocator(PYMEM_DOMAIN_RAW, &s_orig_pymalloc_allocators.raw);
    PyMem_GetAllocator(PYMEM_DOMAIN_MEM, &s_orig_pymalloc_allocators.mem);
    PyMem_GetAllocator(PYMEM_DOMAIN_OBJ, &s_orig_pymalloc_allocators.obj);
    alloc.ctx = &s_orig_pymalloc_allocators.raw;
    PyMem_SetAllocator(PYMEM_DOMAIN_RAW, &alloc);
    alloc.ctx = &s_orig_pymalloc_allocators.mem;
    PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &alloc);
    alloc.ctx = &s_orig_pymalloc_allocators.obj;
    PyMem_SetAllocator(PYMEM_DOMAIN_OBJ, &alloc);
}

void
Tracker::unregisterPymallocHooks() const noexcept
{
    assert(d_trace_python_allocators);
    PyMem_SetAllocator(PYMEM_DOMAIN_RAW, &s_orig_pymalloc_allocators.raw);
    PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &s_orig_pymalloc_allocators.mem);
    PyMem_SetAllocator(PYMEM_DOMAIN_OBJ, &s_orig_pymalloc_allocators.obj);
}

// Trace Function interface

int
PyTraceFunction(
        [[maybe_unused]] PyObject* obj,
        PyFrameObject* frame,
        int what,
        [[maybe_unused]] PyObject* arg)
{
    RecursionGuard guard;
    if (!Tracker::isActive()) {
        return 0;
    }

    switch (what) {
        case PyTrace_CALL: {
            return t_python_stack_tracker.pushPythonFrame(frame);
        }
        case PyTrace_RETURN: {
            t_python_stack_tracker.popPythonFrame();
            break;
        }
        default:
            break;
    }
    return 0;
}

void
install_trace_function()
{
    assert(PyGILState_Check());
    RecursionGuard guard;
    // Don't clear the python stack if we have already registered the tracking
    // function with the current thread.
    PyThreadState* ts = PyThreadState_Get();
    if (ts->c_profilefunc == PyTraceFunction) {
        return;
    }
    PyEval_SetProfile(PyTraceFunction, PyLong_FromLong(123));
    t_python_stack_tracker.reset(PyEval_GetFrame());
}

}  // namespace memray::tracking_api
