#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cassert>

#ifdef __linux__
#    include <link.h>
#elif defined(__APPLE__)
#    include "macho_utils.h"
#    include <mach/mach.h>
#    include <mach/task.h>
#endif

#include <algorithm>
#include <mutex>
#include <type_traits>
#include <unistd.h>

#include "compat.h"
#include "exceptions.h"
#include "hooks.h"
#include "record_writer.h"
#include "records.h"
#include "tracking_api.h"

using namespace memray::exception;
using namespace std::chrono_literals;

namespace {

#ifdef __linux__
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
#endif

}  // namespace

namespace memray::tracking_api {

MEMRAY_FAST_TLS thread_local bool RecursionGuard::isActive = false;

static inline thread_id_t
generate_next_tid()
{
    static std::atomic<thread_id_t> s_tid_counter = 0;
    return ++s_tid_counter;
}

MEMRAY_FAST_TLS thread_local thread_id_t t_tid = generate_next_tid();

static inline thread_id_t
thread_id()
{
    return t_tid;
}

// Tracker interface

// This class must have a trivial destructor (and therefore all its instance
// attributes must be POD). This is required because the libc implementation
// can perform allocations even after the thread local variables for a thread
// have been destroyed. If a TLS variable that is not trivially destructable is
// accessed after that point by our allocation hooks, it will be resurrected,
// and then it will be freed when the thread dies, but its destructor either
// won't be called at all, or will be called on freed memory when some
// arbitrary future thread is destroyed (if the pthread struct is reused for
// another thread).
class PythonStackTracker
{
  private:
    PythonStackTracker() = default;

    enum class FrameState {
        NOT_EMITTED = 0,
        EMITTED_BUT_LINE_NUMBER_MAY_HAVE_CHANGED = 1,
        EMITTED_AND_LINE_NUMBER_HAS_NOT_CHANGED = 2,
    };

    struct LazilyEmittedFrame
    {
        PyFrameObject* frame;
        RawFrame raw_frame_record;
        FrameState state;
    };

  public:
    static bool s_greenlet_tracking_enabled;
    static bool s_native_tracking_enabled;

    static void installProfileHooks();
    static void removeProfileHooks();

    void clear();

    static PythonStackTracker& get();
    void emitPendingPushesAndPops();
    void invalidateMostRecentFrameLineNumber();
    int pushPythonFrame(PyFrameObject* frame);
    void popPythonFrame();

    void installGreenletTraceFunctionIfNeeded();
    void handleGreenletSwitch(PyObject* from, PyObject* to);

  private:
    // Fetch the thread-local stack tracker without checking if its stack needs to be reloaded.
    static PythonStackTracker& getUnsafe();

    static std::vector<LazilyEmittedFrame> pythonFrameToStack(PyFrameObject* current_frame);
    static void recordAllStacks();
    void reloadStackIfTrackerChanged();

    void pushLazilyEmittedFrame(const LazilyEmittedFrame& frame);

    static std::mutex s_mutex;
    static std::unordered_map<PyThreadState*, std::vector<LazilyEmittedFrame>> s_initial_stack_by_thread;
    static std::atomic<unsigned int> s_tracker_generation;

    uint32_t d_num_pending_pops{};
    uint32_t d_tracker_generation{};
    std::vector<LazilyEmittedFrame>* d_stack{};
    bool d_greenlet_hooks_installed{};
};

bool PythonStackTracker::s_greenlet_tracking_enabled{false};
bool PythonStackTracker::s_native_tracking_enabled{false};

std::mutex PythonStackTracker::s_mutex;
std::unordered_map<PyThreadState*, std::vector<PythonStackTracker::LazilyEmittedFrame>>
        PythonStackTracker::s_initial_stack_by_thread;
std::atomic<unsigned int> PythonStackTracker::s_tracker_generation;

PythonStackTracker&
PythonStackTracker::get()
{
    PythonStackTracker& ret = getUnsafe();
    ret.reloadStackIfTrackerChanged();
    return ret;
}

PythonStackTracker&
PythonStackTracker::getUnsafe()
{
    // See giant comment above.
    static_assert(std::is_trivially_destructible<PythonStackTracker>::value);
    MEMRAY_FAST_TLS thread_local PythonStackTracker t_python_stack_tracker;
    return t_python_stack_tracker;
}

void
PythonStackTracker::emitPendingPushesAndPops()
{
    if (!d_stack) {
        return;
    }

    // At any time, the stack contains (in this order):
    // Any number of EMITTED_AND_LINE_NUMBER_HAS_NOT_CHANGED frames
    // 0 or 1 EMITTED_BUT_LINE_NUMBER_MAY_HAVE_CHANGED frame
    // Any number of NOT_EMITTED frames

    auto it = d_stack->rbegin();
    for (; it != d_stack->rend(); ++it) {
        if (it->state == FrameState::NOT_EMITTED) {
            it->raw_frame_record.lineno = PyFrame_GetLineNumber(it->frame);
        } else if (it->state == FrameState::EMITTED_BUT_LINE_NUMBER_MAY_HAVE_CHANGED) {
            int lineno = PyFrame_GetLineNumber(it->frame);
            if (lineno != it->raw_frame_record.lineno) {
                // Line number was wrong; emit an artificial pop so we can push
                // back in with the right line number.
                d_num_pending_pops++;
                it->state = FrameState::NOT_EMITTED;
                it->raw_frame_record.lineno = lineno;
            } else {
                it->state = FrameState::EMITTED_AND_LINE_NUMBER_HAS_NOT_CHANGED;
                break;
            }
        } else {
            assert(it->state == FrameState::EMITTED_AND_LINE_NUMBER_HAS_NOT_CHANGED);
            break;
        }
    }
    auto first_to_emit = it.base();

    Tracker* tracker = Tracker::getTracker();
    if (tracker) {
        // Emit pending pops
        if (d_num_pending_pops) {
            tracker->popFrames(d_num_pending_pops);
            d_num_pending_pops = 0;
        }

        // Emit pending pushes
        for (auto to_emit = first_to_emit; to_emit != d_stack->end(); ++to_emit) {
            if (!tracker->pushFrame(to_emit->raw_frame_record)) {
                break;
            }
            to_emit->state = FrameState::EMITTED_AND_LINE_NUMBER_HAS_NOT_CHANGED;
        }
    }

    invalidateMostRecentFrameLineNumber();
}

void
PythonStackTracker::invalidateMostRecentFrameLineNumber()
{
    // As bytecode instructions are executed, the line number in the most
    // recent Python frame can change without us finding out. Cache its line
    // number, but verify it the next time this frame might need to be emitted.
    if (d_stack && !d_stack->empty()
        && d_stack->back().state == FrameState::EMITTED_AND_LINE_NUMBER_HAS_NOT_CHANGED)
    {
        d_stack->back().state = FrameState::EMITTED_BUT_LINE_NUMBER_MAY_HAVE_CHANGED;
    }
}

void
PythonStackTracker::reloadStackIfTrackerChanged()
{
    // Note: this function does not require the GIL.
    if (d_tracker_generation == s_tracker_generation) {
        return;
    }

    // If we reach this point, a new Tracker was installed by another thread,
    // which also captured our Python stack. Trust it, ignoring any stack we
    // already hold (since the stack we hold could be incorrect if tracking
    // stopped and later restarted underneath our still-running thread).

    if (d_stack) {
        d_stack->clear();
    }
    d_num_pending_pops = 0;

    std::vector<LazilyEmittedFrame> correct_stack;

    {
        std::unique_lock<std::mutex> lock(s_mutex);
        d_tracker_generation = s_tracker_generation;

        auto it = s_initial_stack_by_thread.find(PyGILState_GetThisThreadState());
        if (it != s_initial_stack_by_thread.end()) {
            it->second.swap(correct_stack);
            s_initial_stack_by_thread.erase(it);
        }
    }

    // Iterate in reverse so that we push the most recent call last
    for (auto frame_it = correct_stack.rbegin(); frame_it != correct_stack.rend(); ++frame_it) {
        pushLazilyEmittedFrame(*frame_it);
    }
}

int
PythonStackTracker::pushPythonFrame(PyFrameObject* frame)
{
    installGreenletTraceFunctionIfNeeded();

    PyCodeObject* code = compat::frameGetCode(frame);
    const char* function = PyUnicode_AsUTF8(code->co_name);
    if (function == nullptr) {
        return -1;
    }

    const char* filename = PyUnicode_AsUTF8(code->co_filename);
    if (filename == nullptr) {
        return -1;
    }

    // If native tracking is not enabled, treat every frame as an entry frame.
    // It doesn't matter to the reader, and is more efficient.
    bool is_entry_frame = !s_native_tracking_enabled || compat::isEntryFrame(frame);
    pushLazilyEmittedFrame({frame, {function, filename, 0, is_entry_frame}, FrameState::NOT_EMITTED});
    return 0;
}

void
PythonStackTracker::pushLazilyEmittedFrame(const LazilyEmittedFrame& frame)
{
    // Note: this function does not require the GIL.
    if (!d_stack) {
        d_stack = new std::vector<LazilyEmittedFrame>;
        d_stack->reserve(1024);
    }
    d_stack->push_back(frame);
}

void
PythonStackTracker::popPythonFrame()
{
    installGreenletTraceFunctionIfNeeded();

    if (!d_stack || d_stack->empty()) {
        return;
    }

    if (d_stack->back().state != FrameState::NOT_EMITTED) {
        d_num_pending_pops += 1;
        assert(d_num_pending_pops != 0);  // Ensure we didn't overflow.
    }
    d_stack->pop_back();
    invalidateMostRecentFrameLineNumber();
}

void
PythonStackTracker::installGreenletTraceFunctionIfNeeded()
{
    if (!s_greenlet_tracking_enabled || d_greenlet_hooks_installed) {
        return;  // Nothing to do.
    }

    assert(PyGILState_Check());

    RecursionGuard guard;

    // Borrowed reference
    PyObject* modules = PySys_GetObject("modules");
    if (!modules) {
        return;
    }

    // Borrowed reference
    // Look directly at `sys.modules` since we only want to do something if
    // `greenlet._greenlet` has already been imported.
    PyObject* _greenlet = PyDict_GetItemString(modules, "greenlet._greenlet");
    if (!_greenlet) {
        // Before greenlet 1.0, the extension module was just named "greenlet"
        _greenlet = PyDict_GetItemString(modules, "greenlet");
        if (!_greenlet) {
            return;
        }
    }

    // Borrowed reference
    PyObject* _memray = PyDict_GetItemString(modules, "memray._memray");
    if (!_memray) {
        return;
    }

    PyObject* ret = PyObject_CallMethod(
            _greenlet,
            "settrace",
            "N",
            PyObject_GetAttrString(_memray, "greenlet_trace_function"));
    Py_XDECREF(ret);

    if (!ret) {
        // This might be hit from PyGILState_Ensure when a new thread state is
        // created on a C thread, so we can't reasonably raise the exception.
        PyErr_Print();
        _exit(1);
    }

    // Note: guarded by the GIL
    d_greenlet_hooks_installed = true;

    static bool warned = false;
    if (!warned) {
        warned = true;

        PyObject* res = PyObject_CallMethod(_memray, "print_greenlet_warning", nullptr);
        Py_XDECREF(res);
        if (!res) {
            PyErr_Print();
            _exit(1);
        }
    }
}

void
PythonStackTracker::handleGreenletSwitch(PyObject* from, PyObject* to)
{
    RecursionGuard guard;

    // Clear any old TLS stack, emitting pops for frames that had been pushed.
    if (d_stack) {
        d_num_pending_pops += std::count_if(d_stack->begin(), d_stack->end(), [](const auto& f) {
            return f.state != FrameState::NOT_EMITTED;
        });
        d_stack->clear();
        emitPendingPushesAndPops();
    }

    // Save current TID on old greenlet. Print errors but otherwise ignore them.
    PyObject* tid = PyLong_FromUnsignedLong(t_tid);
    if (!tid || 0 != PyObject_SetAttrString(from, "_memray_tid", tid)) {
        PyErr_Print();
    }
    Py_XDECREF(tid);

    // Restore TID from new greenlet, or generate a new one. Ignore errors:
    // maybe we haven't seen this TID before, or maybe someone overwrote our
    // attribute, but either way we can recover by generating a new one.
    tid = PyObject_GetAttrString(to, "_memray_tid");
    if (!tid || !PyLong_CheckExact(tid)) {
        PyErr_Clear();
        t_tid = generate_next_tid();
    } else {
        t_tid = PyLong_AsUnsignedLong(tid);
    }
    Py_XDECREF(tid);

    // Re-create our TLS stack from our Python frames, most recent last.
    // Note: `frame` may be null; the new greenlet may not have a Python stack.
    PyFrameObject* frame = PyEval_GetFrame();

    std::vector<PyFrameObject*> stack;
    while (frame) {
        stack.push_back(frame);
        frame = compat::frameGetBack(frame);
    }

    std::for_each(stack.rbegin(), stack.rend(), [this](auto& frame) { pushPythonFrame(frame); });
}

std::unique_ptr<std::mutex> Tracker::s_mutex(new std::mutex);
pthread_key_t Tracker::s_native_unwind_vector_key;
std::unique_ptr<Tracker> Tracker::s_instance_owner;
std::atomic<Tracker*> Tracker::s_instance = nullptr;

std::vector<PythonStackTracker::LazilyEmittedFrame>
PythonStackTracker::pythonFrameToStack(PyFrameObject* current_frame)
{
    std::vector<LazilyEmittedFrame> stack;

    while (current_frame) {
        PyCodeObject* code = compat::frameGetCode(current_frame);

        const char* function = PyUnicode_AsUTF8(code->co_name);
        if (function == nullptr) {
            return {};
        }

        const char* filename = PyUnicode_AsUTF8(code->co_filename);
        if (filename == nullptr) {
            return {};
        }

        // If native tracking is not enabled, treat every frame as an entry frame.
        // It doesn't matter to the reader, and is more efficient.
        bool entry = !s_native_tracking_enabled || compat::isEntryFrame(current_frame);
        stack.push_back({current_frame, {function, filename, 0, entry}, FrameState::NOT_EMITTED});
        current_frame = compat::frameGetBack(current_frame);
    }

    return stack;
}

void
PythonStackTracker::recordAllStacks()
{
    assert(PyGILState_Check());

    // Record the current Python stack of every thread
    std::unordered_map<PyThreadState*, std::vector<LazilyEmittedFrame>> stack_by_thread;
    for (PyThreadState* tstate =
                 PyInterpreterState_ThreadHead(compat::threadStateGetInterpreter(PyThreadState_Get()));
         tstate != nullptr;
         tstate = PyThreadState_Next(tstate))
    {
        PyFrameObject* frame = compat::threadStateGetFrame(tstate);
        if (!frame) {
            continue;
        }

        stack_by_thread[tstate] = pythonFrameToStack(frame);
        if (PyErr_Occurred()) {
            throw std::runtime_error("Failed to capture a thread's Python stack");
        }
    }

    std::unique_lock<std::mutex> lock(s_mutex);
    s_initial_stack_by_thread.swap(stack_by_thread);

    // Register that tracking has begun (again?), telling threads to sync their
    // TLS from these captured stacks. Update this atomically with the map, or
    // a thread that's 2 generations behind could grab the new stacks with the
    // previous generation number and immediately think they're out of date.
    s_tracker_generation++;
}

void
PythonStackTracker::installProfileHooks()
{
    assert(PyGILState_Check());

    // Uninstall any existing profile function in all threads. Do this before
    // installing ours, since we could lose the GIL if the existing profile arg
    // has a __del__ that gets called. We must hold the GIL for the entire time
    // we capture threads' stacks and install our trace function into them, so
    // their stacks can't change after we've captured them and before we've
    // installed our profile function that utilizes the captured stacks, and so
    // they can't start profiling before we capture their stack and miss it.
    compat::setprofileAllThreads(nullptr, nullptr);

    // Find and record the Python stack for all existing threads.
    recordAllStacks();

    // Install our profile trampoline in all existing threads.
    compat::setprofileAllThreads(PyTraceTrampoline, nullptr);
}

void
PythonStackTracker::removeProfileHooks()
{
    assert(PyGILState_Check());
    compat::setprofileAllThreads(nullptr, nullptr);
    std::unique_lock<std::mutex> lock(s_mutex);
    s_initial_stack_by_thread.clear();
}

void
PythonStackTracker::clear()
{
    if (!d_stack) {
        return;
    }

    while (!d_stack->empty()) {
        d_num_pending_pops += (d_stack->back().state != FrameState::NOT_EMITTED);
        d_stack->pop_back();
    }
    emitPendingPushesAndPops();
    delete d_stack;
    d_stack = nullptr;
}

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
    static std::once_flag once;
    call_once(once, [] {
        // We use the pthread TLS API for this vector because we must be able
        // to re-create it while TLS destructors are running (a destructor can
        // call malloc, hitting our malloc hook). POSIX guarantees multiple
        // rounds of TLS destruction if destructors call pthread_setspecific.
        // Note: If this raises an exception, the call_once can be retried.
        if (0 != pthread_key_create(&s_native_unwind_vector_key, [](void* data) {
                delete static_cast<std::vector<NativeTrace::ip_t>*>(data);
            }))
        {
            throw std::runtime_error{"Failed to create pthread key"};
        }

        hooks::ensureAllHooksAreValid();
        NativeTrace::setup();
    });

    d_writer->setMainTidAndSkippedFrames(thread_id(), computeMainTidSkip());
    if (!d_writer->writeHeader(false)) {
        throw IoError{"Failed to write output header"};
    }

    RecursionGuard guard;
    updateModuleCacheImpl();

    PythonStackTracker::s_native_tracking_enabled = native_traces;
    PythonStackTracker::installProfileHooks();
    if (d_trace_python_allocators) {
        registerPymallocHooks();
    }
    d_background_thread = std::make_unique<BackgroundThread>(d_writer, memory_interval);
    d_background_thread->start();

    d_patcher.overwrite_symbols();
}

Tracker::~Tracker()
{
    RecursionGuard guard;
    tracking_api::Tracker::deactivate();

    PythonStackTracker::s_native_tracking_enabled = false;
    d_background_thread->stop();

    {
        std::scoped_lock<std::mutex> lock(*s_mutex);
        d_patcher.restore_symbols();
    }

    if (Py_IsInitialized() && !compat::isPythonFinalizing()) {
        PyGILState_STATE gstate;
        gstate = PyGILState_Ensure();

        if (d_trace_python_allocators) {
            std::scoped_lock<std::mutex> lock(*s_mutex);
            unregisterPymallocHooks();
        }

        PythonStackTracker::removeProfileHooks();

        PyGILState_Release(gstate);
    }

    std::scoped_lock<std::mutex> lock(*s_mutex);
    d_writer->writeTrailer();
    d_writer->writeHeader(true);
    d_writer.reset();
}

Tracker::BackgroundThread::BackgroundThread(
        std::shared_ptr<RecordWriter> record_writer,
        unsigned int memory_interval)
: d_writer(std::move(record_writer))
, d_memory_interval(memory_interval)
{
#ifdef __linux__
    d_procs_statm.open("/proc/self/statm");
    if (!d_procs_statm) {
        throw IoError{"Failed to open /proc/self/statm"};
    }
#endif
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
#ifdef __linux__
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
#elif defined(__APPLE__)
    struct mach_task_basic_info info;
    mach_msg_type_number_t infoCount = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &infoCount)
        != KERN_SUCCESS)
        return (size_t)0L; /* Can't access? */
    return (size_t)info.resident_size;
#else
    return 0;
#endif
}

bool
Tracker::BackgroundThread::captureMemorySnapshot()
{
    auto now = timeElapsed();
    size_t rss = getRSS();
    if (rss == 0) {
        std::cerr << "Failed to detect RSS, deactivating tracking" << std::endl;
        Tracker::deactivate();
        return false;
    }

    std::lock_guard<std::mutex> lock(*s_mutex);
    if (!d_writer->writeRecord(MemoryRecord{now, rss})) {
        std::cerr << "Failed to write output, deactivating tracking" << std::endl;
        Tracker::deactivate();
        return false;
    }

    return true;
}

void
Tracker::BackgroundThread::start()
{
    assert(d_thread.get_id() == std::thread::id());

    if (!captureMemorySnapshot()) {
        return;
    }

    d_thread = std::thread([&]() {
        RecursionGuard::isActive = true;
        while (true) {
            {
                std::unique_lock<std::mutex> lock(d_mutex);
                d_cv.wait_for(lock, d_memory_interval * 1ms, [this]() { return d_stop; });
                if (d_stop) {
                    return;
                }
            }

            if (!captureMemorySnapshot()) {
                return;
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
    }
    d_cv.notify_one();
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
    (void)s_instance_owner.release();

    // Likewise, leak our old mutex, and re-create it.
    (void)s_mutex.release();
    s_mutex.reset(new std::mutex);

    // Save a reference to the old tracker (if any), then unset our singleton.
    Tracker* old_tracker = s_instance;
    Tracker::deactivate();

    // If we inherited an active tracker, try to clone its record writer.
    std::unique_ptr<RecordWriter> new_writer;
    if (old_tracker && old_tracker->d_follow_fork) {
        new_writer = old_tracker->d_writer->cloneInChildProcess();
    }

    if (!new_writer) {
        // Either tracking wasn't active, or the tracker was using a sink that
        // can't be cloned. Leave our singleton unset and bail out. Note that
        // the old tracker's hooks may still be installed.  If this process
        // exits, trackDeallocation will be called to track the deallocation of
        // s_mutex when the process's globals are destroyed! To handle this,
        // the hooks must check the (static) isActive() flag before acquiring
        // s_mutex or calling any methods on the now null tracker singleton.
        RecursionGuard::isActive = false;
        return;
    }

    // Re-enable tracking with a brand new tracker.
    // Disable tracking until the new tracker is fully installed.
    s_instance_owner.reset(new Tracker(
            std::move(new_writer),
            old_tracker->d_unwind_native_frames,
            old_tracker->d_memory_interval,
            old_tracker->d_follow_fork,
            old_tracker->d_trace_python_allocators));
    Tracker::activate();
    RecursionGuard::isActive = false;
}

size_t
Tracker::computeMainTidSkip()
{
    // Determine how many frames from the current stack to elide from our
    // reported stack traces. This avoids showing the user frames above the one
    // that called `Tracker.__enter__`.
    assert(PyGILState_Check());

    PyFrameObject* frame = PyEval_GetFrame();

    size_t num_frames = 0;
    while (frame) {
        ++num_frames;
        frame = compat::frameGetBack(frame);
    }

    assert(num_frames > 0);
    return num_frames - 1;
}

bool
Tracker::areNativeTracesEnabled()
{
    return PythonStackTracker::s_native_tracking_enabled;
}

void
Tracker::trackAllocationImpl(
        void* ptr,
        size_t size,
        hooks::Allocator func,
        const std::optional<NativeTrace>& trace)
{
    registerCachedThreadName();
    PythonStackTracker::get().emitPendingPushesAndPops();

    if (d_unwind_native_frames) {
        frame_id_t native_index = 0;

        // Skip the internal frames so we don't need to filter them later.
        if (trace && trace.value().size()) {
            native_index =
                    d_native_trace_tree.getTraceIndex(trace.value(), [&](frame_id_t ip, uint32_t index) {
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
    registerCachedThreadName();
    AllocationRecord record{reinterpret_cast<uintptr_t>(ptr), size, func};
    if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
        std::cerr << "Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::invalidate_module_cache_impl()
{
    d_patcher.overwrite_symbols();
    updateModuleCacheImpl();
}

#ifdef __linux__
static int
dl_iterate_phdr_callback(struct dl_phdr_info* info, [[maybe_unused]] size_t size, void* data)
{
    auto& mappings = *reinterpret_cast<std::vector<ImageSegments>*>(data);
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

    mappings.push_back({filename, info->dlpi_addr, std::move(segments)});
    return 0;
}
#endif

void
Tracker::updateModuleCacheImpl()
{
    if (!d_unwind_native_frames) {
        return;
    }

    static size_t s_last_mappings_size = 20;

    std::vector<ImageSegments> mappings;
    mappings.reserve(s_last_mappings_size + 1);

#ifdef __linux__
    dl_iterate_phdr(&dl_iterate_phdr_callback, &mappings);
#elif defined(__APPLE__)
    uint32_t c = _dyld_image_count();
    for (uint32_t i = 0; i < c; i++) {
        const struct mach_header* header = _dyld_get_image_header(i);
        auto slide = static_cast<uintptr_t>(_dyld_get_image_vmaddr_slide(i));
        const char* image_name = _dyld_get_image_name(i);
        std::vector<Segment> segments;

        const segment_command_t* current_segment_cmd;
        uintptr_t current_cmd = reinterpret_cast<uintptr_t>(header) + sizeof(mach_header_t);
        for (uint j = 0; j < header->ncmds; j++, current_cmd += current_segment_cmd->cmdsize) {
            current_segment_cmd = reinterpret_cast<const segment_command_t*>(current_cmd);
            if (current_segment_cmd->cmd == ARCH_LC_SEGMENT) {
                segments.emplace_back(Segment{current_segment_cmd->vmaddr, current_segment_cmd->vmsize});
            }
        }

        mappings.push_back({image_name, slide, std::move(segments)});
    }
#endif

    s_last_mappings_size = mappings.size();

    if (!d_writer->writeMappings(mappings)) {
        std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
        Tracker::deactivate();
        return;
    }
}

void
Tracker::registerThreadNameImpl(const char* name)
{
    RecursionGuard guard;
    dropCachedThreadName();
    if (!d_writer->writeThreadSpecificRecord(thread_id(), ThreadRecord{name})) {
        std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::registerCachedThreadName()
{
    if (d_cached_thread_names.empty()) {
        return;
    }

    auto it = d_cached_thread_names.find((uint64_t)(pthread_self()));
    if (it != d_cached_thread_names.end()) {
        auto& name = it->second;
        if (!d_writer->writeThreadSpecificRecord(thread_id(), ThreadRecord{name.c_str()})) {
            std::cerr << "memray: Failed to write output, deactivating tracking" << std::endl;
            deactivate();
        }
        d_cached_thread_names.erase(it);
    }
}

void
Tracker::dropCachedThreadName()
{
    d_cached_thread_names.erase((uint64_t)(pthread_self()));
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
    // NOTE: Tracker::s_mutex must be held
    s_instance = s_instance_owner.get();
}

void
Tracker::deactivate()
{
    s_instance = nullptr;
}

bool
Tracker::isActive()
{
    return s_instance != nullptr;
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
    s_instance_owner.reset(new Tracker(
            std::move(record_writer),
            native_traces,
            memory_interval,
            follow_fork,
            trace_python_allocators));

    std::unique_lock<std::mutex> lock(*s_mutex);
    tracking_api::Tracker::activate();
    Py_RETURN_NONE;
}

PyObject*
Tracker::destroyTracker()
{
    // Note: the GIL is used for synchronization of the singleton
    s_instance_owner.reset();
    Py_RETURN_NONE;
}

Tracker*
Tracker::getTracker()
{
    return s_instance;
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

PyObject*
create_profile_arg()
{
    // Borrowed reference
    PyObject* memray_ext = PyDict_GetItemString(PyImport_GetModuleDict(), "memray._memray");
    if (!memray_ext) {
        return nullptr;
    }

    return PyObject_CallMethod(memray_ext, "ProfileFunctionGuard", nullptr);
}

// Called when profiling is initially enabled in each thread.
int
PyTraceTrampoline(PyObject* obj, PyFrameObject* frame, int what, [[maybe_unused]] PyObject* arg)
{
    assert(PyGILState_Check());
    RecursionGuard guard;

    PyObject* profileobj = create_profile_arg();
    if (!profileobj) {
        return -1;
    }
    PyEval_SetProfile(PyTraceFunction, profileobj);
    Py_DECREF(profileobj);

    return PyTraceFunction(obj, frame, what, profileobj);
}

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

    if (frame != PyEval_GetFrame()) {
        // This should only happen for the phony frames produced by Cython
        // extension modules that were compiled with `profile=True`.
        return 0;
    }

    switch (what) {
        case PyTrace_CALL: {
            return PythonStackTracker::get().pushPythonFrame(frame);
        }
        case PyTrace_RETURN: {
            PythonStackTracker::get().popPythonFrame();
            break;
        }
        default:
            break;
    }
    return 0;
}

void
Tracker::forgetPythonStack()
{
    if (!Tracker::isActive()) {
        return;
    }

    // Grab the Tracker lock, as this may need to write pushes/pops.
    std::unique_lock<std::mutex> lock(*s_mutex);
    RecursionGuard guard;
    PythonStackTracker::get().clear();
}

void
Tracker::beginTrackingGreenlets()
{
    assert(PyGILState_Check());
    PythonStackTracker::s_greenlet_tracking_enabled = true;
}

void
Tracker::handleGreenletSwitch(PyObject* from, PyObject* to)
{
    // We must stop tracking the stack once our trace function is uninstalled.
    // Otherwise, we'd keep referencing frames after they're destroyed.
    PyThreadState* ts = PyThreadState_Get();
    if (ts->c_profilefunc != PyTraceFunction) {
        return;
    }

    // Grab the Tracker lock, as this may need to write pushes/pops.
    std::unique_lock<std::mutex> lock(*s_mutex);
    RecursionGuard guard;

    PythonStackTracker::get().handleGreenletSwitch(from, to);
}

void
install_trace_function()
{
    assert(PyGILState_Check());
    RecursionGuard guard;
    // Don't clear the python stack if we have already registered the tracking
    // function with the current thread. This happens when PyGILState_Ensure is
    // called and a thread state with our hooks installed already exists.
    PyThreadState* ts = PyThreadState_Get();
    if (ts->c_profilefunc == PyTraceFunction) {
        return;
    }

    PyObject* profileobj = create_profile_arg();
    if (!profileobj) {
        return;
    }
    PyEval_SetProfile(PyTraceFunction, profileobj);
    Py_DECREF(profileobj);

    PyFrameObject* frame = PyEval_GetFrame();

    // Push all of our Python frames, most recent last.  If we reached here
    // from PyGILState_Ensure on a C thread there may be no Python frames.
    std::vector<PyFrameObject*> stack;
    while (frame) {
        stack.push_back(frame);
        frame = compat::frameGetBack(frame);
    }

    auto& python_stack_tracker = PythonStackTracker::get();
    for (auto frame_it = stack.rbegin(); frame_it != stack.rend(); ++frame_it) {
        python_stack_tracker.pushPythonFrame(*frame_it);
    }

    python_stack_tracker.installGreenletTraceFunctionIfNeeded();
}

}  // namespace memray::tracking_api
