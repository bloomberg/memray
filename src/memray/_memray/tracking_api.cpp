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

extern "C" Py_ssize_t
_PyEval_RequestCodeExtraIndex(freefunc free);
extern "C" int
_PyCode_GetExtra(PyObject* code, Py_ssize_t index, void** extra);
extern "C" int
_PyCode_SetExtra(PyObject* code, Py_ssize_t index, void* extra);

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

class StopTheWorldGuard
{
  public:
    StopTheWorldGuard()
    : d_interp(PyGILState_GetThisThreadState()->interp)
    {
        memray::compat::stopTheWorld(d_interp);
    }

    ~StopTheWorldGuard()
    {
        memray::compat::startTheWorld(d_interp);
    }

  private:
    StopTheWorldGuard(const StopTheWorldGuard&) = delete;
    StopTheWorldGuard& operator=(const StopTheWorldGuard&) = delete;
    StopTheWorldGuard(StopTheWorldGuard&&) = delete;

    PyInterpreterState* d_interp;
};

#if PY_VERSION_HEX < 0x030C0000
Py_ssize_t s_extra_index = -1;
#endif

}  // namespace

namespace memray::tracking_api {

#ifdef __linux__
MEMRAY_FAST_TLS thread_local bool RecursionGuard::_isActive = false;
#else
pthread_key_t RecursionGuard::isActiveKey;
#endif

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
// To prevent that, we create the vector in one method, pushLazilyEmittedFrame.
// All other methods access a pointer called `d_stack` that is set to the TLS
// stack when it is created by pushLazilyEmittedFrame, and set to a null
// pointer when the TLS stack is destroyed.
//
// This can result in this class being constructed during thread teardown, but
// that doesn't cause the same problem because it has a trivial destructor.
class PythonStackTracker
{
  private:
    PythonStackTracker() = default;

    class LazilyEmittedFrame
    {
      public:
        LazilyEmittedFrame(PyFrameObject* frame);

        // Has this frame been emitted already?
        bool isEmitted() const;

        // Update the instruction offset from the frame, if possible.
        // If the offset changes, mark the frame as not emitted.
        void updateInstructionOffset();

        // Drop our reference to the frame, freezing the instruction offset.
        void freezeInstructionOffset();

        // Has the instruction offset been frozen?
        bool isFrozen() const;

        // If we haven't already, register the held code object, saving its ID
        // and dropping our borrowed reference to the code object.
        void resolveCodeObjectId(Tracker& tracker);

        // Emit this frame if it hasn't already been emitted.
        // Returns true on success or if the frame was already emitted.
        bool emit(Tracker& tracker);

      private:
        bool d_emitted{false};

        // Threads' initial stacks can have calls to sys.settrace tracing
        // functions which our profile function won't see get popped. We can't
        // hold borrowed references to those frames; we won't know when they
        // die. For frames on those initial stacks, we resolve the instruction
        // offset once up front then set `d_frame` to a null pointer.
        PyFrameObject* d_frame{};

        // Likewise, we can't hold borrowed references to the code objects
        // owned by initial frames. We drop our reference once a code object id
        // has been assigned. For initial frames, we assign that ID while the
        // world is stopped, before the reference could become invalid.
        PyCodeObject* d_code{};

        // Information extracted from PyCodeObject while the GIL is held,
        // and later used while the GIL may not be held.
        CodeObject d_code_info{};

        // The unique ID assigned by the Tracker for the associated code object
        code_object_id_t d_code_object_id{};

        // Whether this frame is an entry frame for native unwinding purposes.
        bool d_is_entry_frame{};

        // The frame's current bytecode offset within the code object.
        int d_instruction_offset{};
    };

  public:
    static bool s_greenlet_tracking_enabled;
    static bool s_native_tracking_enabled;

    static void installProfileHooks();
    static void recordAllStacks(Tracker& tracker);
    static void removeProfileHooks();

    static PythonStackTracker& get();
    void emitPendingPushesAndPops();
    void populateShadowStack();
    void handleTraceEvent(int what, PyFrameObject* frame);

    void installGreenletTraceFunctionIfNeeded();
    void handleGreenletSwitch(PyObject* from, PyObject* to);

  private:
    // Fetch the thread-local stack tracker without checking if its stack needs to be reloaded.
    static PythonStackTracker& getUnsafe();

    static std::vector<LazilyEmittedFrame>
    pythonFrameToStack(PyFrameObject* current_frame, Tracker& tracker);

    void reloadStackIfTrackerChanged();
    void clear();

    void pushLazilyEmittedFrame(const LazilyEmittedFrame& frame);

    int pushPythonFrame(PyFrameObject* frame);
    void popPythonFrame();

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

    if (!d_stack->empty()) {
        PyThreadState* ts = PyGILState_GetThisThreadState();
        if (!ts || ts->c_profilefunc != PyTraceFunction) {
            // Note: clear() will call back into emitPendingPushesAndPops() to
            //       emit the pops, but we won't call back into clear() because
            //       the stack has already been emptied.
            clear();
            return;
        }
    }

#ifdef Py_GIL_DISABLED
    PyGILState_STATE gstate = PyGILState_Ensure();
#endif

    // At any time, the stack contains (from beginning to end) any number of
    // emitted frames followed by any number of not yet emitted frames.
    // The line number of the last emitted frame may be out of date.
    // We iterate in reverse order, to see the not emitted frames first.
    // After the loop, `it` points to the first frame not to need emitting,
    // or to `rend()` if all frames need emitting.
    auto it = d_stack->rbegin();
    for (; it != d_stack->rend(); ++it) {
        // Note: updateInstructionOffset() may change isEmitted()!
        if (!it->isEmitted()) {
            // Has not been emitted before; now will be the first time.
            it->updateInstructionOffset();
        } else {
            // Has been emitted...
            it->updateInstructionOffset();
            if (it->isEmitted()) {
                // ... and the line number didn't change. This and all later
                // frames have been emitted and don't need to be re-emitted.
                break;
            } else {
                // ... but the instruction offset was wrong; emit an artificial
                // pop so we can push back in with the right offset.
                d_num_pending_pops++;

                // The next frame is the first to not need (re)emitting.
                ++it;
                break;
            }
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
            if (!to_emit->emit(*tracker)) {
                break;
            }
        }
    }

#ifdef Py_GIL_DISABLED
    PyGILState_Release(gstate);
#endif
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

void
PythonStackTracker::populateShadowStack()
{
    installGreenletTraceFunctionIfNeeded();

    clear();

    PyFrameObject* frame = PyEval_GetFrame();

    std::vector<PyFrameObject*> stack;
    while (frame) {
        stack.push_back(frame);
        frame = compat::frameGetBack(frame);
    }

    std::for_each(stack.rbegin(), stack.rend(), [this](auto& frame) { pushPythonFrame(frame); });
}

void
PythonStackTracker::handleTraceEvent(int what, PyFrameObject* frame)
{
    installGreenletTraceFunctionIfNeeded();

    if (d_stack && !d_stack->empty() && d_stack->back().isFrozen()) {
        // This stack was set by reloadStackIfTrackerChanged and may have calls
        // to sys.settrace tracing functions on it. Drop it now, replacing it
        // with a stack fetched from PyEval_GetFrame which we know can't have
        // trace function frames on it, and which we can track properly.
        populateShadowStack();

        if (what == PyTrace_CALL) {
            // The stack we just populated includes the frame for this call.
            // Return early to avoid duplicating it.
            return;
        }
    }

    if (what == PyTrace_CALL) {
        pushPythonFrame(frame);
    } else if (what == PyTrace_RETURN) {
        popPythonFrame();
    }
}

int
PythonStackTracker::pushPythonFrame(PyFrameObject* frame)
{
    try {
        pushLazilyEmittedFrame(LazilyEmittedFrame(frame));
        return 0;
    } catch (const std::runtime_error&) {
        return -1;
    }
}

void
PythonStackTracker::pushLazilyEmittedFrame(const LazilyEmittedFrame& frame)
{
    // Note: this function does not require the GIL.
    struct StackCreator
    {
        std::vector<LazilyEmittedFrame> stack;

        StackCreator()
        {
            const size_t INITIAL_PYTHON_STACK_FRAMES = 1024;
            stack.reserve(INITIAL_PYTHON_STACK_FRAMES);
            PythonStackTracker::getUnsafe().d_stack = &stack;
        }
        ~StackCreator()
        {
            PythonStackTracker::getUnsafe().d_stack = nullptr;
        }
    };

    MEMRAY_FAST_TLS static thread_local StackCreator t_stack_creator;
    t_stack_creator.stack.push_back(frame);
    assert(d_stack);  // The above call sets d_stack if it wasn't already set.
}

void
PythonStackTracker::popPythonFrame()
{
    if (!d_stack || d_stack->empty()) {
        return;
    }

    if (d_stack->back().isEmitted()) {
        d_num_pending_pops += 1;
        assert(d_num_pending_pops != 0);  // Ensure we didn't overflow.
    }
    d_stack->pop_back();
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
    this->clear();

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

    populateShadowStack();
}

std::unique_ptr<std::mutex> Tracker::s_mutex(new std::mutex);
pthread_key_t Tracker::s_native_unwind_vector_key;
std::unique_ptr<Tracker> Tracker::s_instance_owner;
std::atomic<Tracker*> Tracker::s_instance = nullptr;

PythonStackTracker::LazilyEmittedFrame::LazilyEmittedFrame(PyFrameObject* frame)
{
    assert(PyGILState_Check());

    d_frame = frame;
    d_code = compat::frameGetCode(frame);
#if PY_VERSION_HEX < 0x030C0000
    if (s_extra_index != -1) {
        void* extra;
        if (-1 == _PyCode_GetExtra((PyObject*)d_code, s_extra_index, &extra)) {
            throw std::runtime_error("Failed to get extra data from code object");
        }
        if (!extra && -1 == _PyCode_SetExtra((PyObject*)d_code, s_extra_index, d_code)) {
            throw std::runtime_error("Failed to set extra data on code object");
        }
    }
#endif

    d_code_info.function_name = PyUnicode_AsUTF8(d_code->co_name);
    if (d_code_info.function_name == nullptr) {
        throw std::runtime_error("Failed to get function name from frame");
    }

    d_code_info.filename = PyUnicode_AsUTF8(d_code->co_filename);
    if (d_code_info.filename == nullptr) {
        throw std::runtime_error("Failed to get filename from frame");
    }

    // Get linetable information
    d_code_info.linetable = compat::codeGetLinetable(d_code, &d_code_info.linetable_size);
    d_code_info.firstlineno = d_code->co_firstlineno;

    // If native tracking is not enabled, treat every frame as an entry frame.
    // It doesn't matter to the reader, and is more efficient.
    d_is_entry_frame = !s_native_tracking_enabled || compat::isEntryFrame(frame);
}

bool
PythonStackTracker::LazilyEmittedFrame::isEmitted() const
{
    return d_emitted;
}

void
PythonStackTracker::LazilyEmittedFrame::updateInstructionOffset()
{
    if (d_frame) {
        auto old_instruction_offset = d_instruction_offset;
        d_instruction_offset = compat::frameGetLasti(d_frame);

        if (d_instruction_offset != old_instruction_offset) {
            d_emitted = false;
        }
    }
}

void
PythonStackTracker::LazilyEmittedFrame::freezeInstructionOffset()
{
    d_frame = nullptr;
}

bool
PythonStackTracker::LazilyEmittedFrame::isFrozen() const
{
    return d_frame == nullptr;
}

void
PythonStackTracker::LazilyEmittedFrame::resolveCodeObjectId(Tracker& tracker)
{
    if (d_code) {
        d_code_object_id = tracker.registerCodeObject(d_code, d_code_info);
        d_code = nullptr;
    }
}

bool
PythonStackTracker::LazilyEmittedFrame::emit(Tracker& tracker)
{
    if (d_emitted) {
        return true;  // Already emitted.
    }

    resolveCodeObjectId(tracker);
    bool ret = tracker.pushFrame(Frame{d_code_object_id, d_instruction_offset, d_is_entry_frame});
    if (ret) {
        d_emitted = true;
    }
    return ret;
}

std::vector<PythonStackTracker::LazilyEmittedFrame>
PythonStackTracker::pythonFrameToStack(PyFrameObject* current_frame, Tracker& tracker)
{
    std::vector<LazilyEmittedFrame> stack;
    while (current_frame) {
        try {
            stack.push_back(LazilyEmittedFrame(current_frame));
        } catch (const std::runtime_error&) {
            return {};
        }

        stack.back().resolveCodeObjectId(tracker);
        stack.back().updateInstructionOffset();
        stack.back().freezeInstructionOffset();
        current_frame = compat::frameGetBack(current_frame);
    }

    return stack;
}

void
PythonStackTracker::recordAllStacks(Tracker& tracker)
{
    // We need to ensure that stacks are captured atomically with respect to
    // incrementing s_tracker_generation and to setting Tracker::isActive().
    // The caller must use the GIL for this in with-GIL builds, and call
    // _PyEval_StopTheWorld in free-threaded builds. Otherwise, the shadow
    // stack may become inconsistent with the true stack for a thread, which
    // leads to frames being used after they've been freed.

    // Additionally, the Tracker mutex must be held, as pythonFrameToStack
    // calls registerCodeObject. The Tracker is an argument as this function
    // is called before tracking is activated and the singleton is installed.

    assert(PyGILState_Check());
    PyThreadState* current_thread = PyThreadState_Get();

    // Record the current Python stack of every thread
    std::unordered_map<PyThreadState*, std::vector<LazilyEmittedFrame>> stack_by_thread;
    for (PyThreadState* tstate =
                 PyInterpreterState_ThreadHead(compat::threadStateGetInterpreter(current_thread));
         tstate != nullptr;
         tstate = PyThreadState_Next(tstate))
    {
        if (tstate == current_thread) {
            // Handled by the call to populateShadowStack in below
            continue;
        }

        PyFrameObject* frame = compat::threadStateGetFrame(tstate);
        if (!frame) {
            continue;
        }

        stack_by_thread[tstate] = pythonFrameToStack(frame, tracker);
        if (PyErr_Occurred()) {
            throw std::runtime_error("Failed to capture a thread's Python stack");
        }
    }

    {
        std::unique_lock<std::mutex> lock(s_mutex);
        s_initial_stack_by_thread.swap(stack_by_thread);

        // Register that tracking has begun (again?), telling threads to sync their
        // TLS from these captured stacks. Update this atomically with the map, or
        // a thread that's 2 generations behind could grab the new stacks with the
        // previous generation number and immediately think they're out of date.
        s_tracker_generation++;
    }

    PythonStackTracker::get().populateShadowStack();
}

void
PythonStackTracker::installProfileHooks()
{
    // Install our profile function in all existing threads. Note that the
    // profile function may begin executing before recordAllStacks is called.
    compat::setprofileAllThreads(PyTraceFunction, nullptr);
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

    d_num_pending_pops +=
            std::count_if(d_stack->begin(), d_stack->end(), [](const auto& f) { return f.isEmitted(); });
    d_stack->clear();
    emitPendingPushesAndPops();
}

Tracker::Tracker(
        std::unique_ptr<RecordWriter> record_writer,
        bool native_traces,
        unsigned int memory_interval,
        bool follow_fork,
        bool trace_python_allocators,
        bool reference_tracking)
: d_writer(std::move(record_writer))
, d_unwind_native_frames(native_traces)
, d_memory_interval(memory_interval)
, d_follow_fork(follow_fork)
, d_trace_python_allocators(trace_python_allocators)
, d_reference_tracking(reference_tracking)
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

#if PY_VERSION_HEX >= 0x030C0000
        PyCode_AddWatcher([](PyCodeEvent event, PyCodeObject* code) {
            if (event == PY_CODE_EVENT_DESTROY) {
                if (RecursionGuard::isActive() || !Tracker::isActive()) {
                    return 0;
                }
                RecursionGuard guard;

                std::unique_lock<std::mutex> lock(*s_mutex);
                Tracker* tracker = Tracker::getTracker();
                if (tracker) {
                    tracker->forgetCodeObject(code);
                }
            }
            return 0;
        });
#else
        s_extra_index = _PyEval_RequestCodeExtraIndex([](void* code) {
            if (RecursionGuard::isActive() || !Tracker::isActive()) {
                return;
            }
            RecursionGuard guard;

            std::unique_lock<std::mutex> lock(*s_mutex);
            Tracker* tracker = Tracker::getTracker();
            if (tracker) {
                tracker->forgetCodeObject((PyCodeObject*)code);
            }
        });
#endif
    });

    d_writer->setMainTidAndSkippedFrames(thread_id(), computeMainTidSkip());
    if (!d_writer->writeHeader(false)) {
        throw IoError{"Failed to write output header"};
    }

    RecursionGuard guard;
    updateModuleCacheImpl();

    PythonStackTracker::s_native_tracking_enabled = native_traces;
    PythonStackTracker::installProfileHooks();
    if (d_reference_tracking) {
        registerReferenceTrackingHooks();
    }
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

        if (d_reference_tracking) {
            std::scoped_lock<std::mutex> lock(*s_mutex);
            unregisterReferenceTrackingHooks();
        }

        if (d_trace_python_allocators) {
            std::scoped_lock<std::mutex> lock(*s_mutex);
            unregisterPymallocHooks();
        }

        PythonStackTracker::removeProfileHooks();

        PyGILState_Release(gstate);
    }

    std::scoped_lock<std::mutex> lock(*s_mutex);
    d_tracked_objects.clear();
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

uint64_t
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
        RecursionGuard::setValue(true);
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
    RecursionGuard::setValue(true);
}

void
Tracker::parentFork()
{
    // We can continue tracking
    RecursionGuard::setValue(false);
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
        RecursionGuard::setValue(false);
        return;
    }

    // Re-enable tracking with a brand new tracker.
    // Disable tracking until the new tracker is fully installed.
    s_instance_owner.reset(new Tracker(
            std::move(new_writer),
            old_tracker->d_unwind_native_frames,
            old_tracker->d_memory_interval,
            old_tracker->d_follow_fork,
            old_tracker->d_trace_python_allocators,
            old_tracker->d_reference_tracking));

    StopTheWorldGuard stop_the_world;
    std::unique_lock<std::mutex> lock(*s_mutex);
    PythonStackTracker::recordAllStacks(*s_instance_owner);
    tracking_api::Tracker::activate();
    RecursionGuard::setValue(false);
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
        AllocationRecord record{reinterpret_cast<uintptr_t>(ptr), size, func, native_index};
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
Tracker::trackObjectImpl(PyObject* obj, int event, const std::optional<NativeTrace>& trace)
{
    registerCachedThreadName();
    PythonStackTracker::get().emitPendingPushesAndPops();

    if (event == 0) {  // Creation event
        d_tracked_objects.emplace(obj);

        if (d_unwind_native_frames) {
            frame_id_t native_index = 0;
            // Skip the internal frames so we don't need to filter them later.
            if (trace && trace.value().size()) {
                native_index = d_native_trace_tree.getTraceIndex(
                        trace.value(),
                        [&](frame_id_t ip, uint32_t index) {
                            return d_writer->writeRecord(UnresolvedNativeFrame{ip, index});
                        });
            }

            ObjectRecord record{reinterpret_cast<uintptr_t>(obj), true, native_index};
            if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
                std::cerr << "Failed to write output, deactivating tracking" << std::endl;
                deactivate();
            }
        } else {
            ObjectRecord record{reinterpret_cast<uintptr_t>(obj), true};
            if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
                std::cerr << "Failed to write output, deactivating tracking" << std::endl;
                deactivate();
            }
        }
    } else {  // Destruction event
        d_tracked_objects.erase(obj);
        ObjectRecord record{reinterpret_cast<uintptr_t>(obj), false};
        if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
            std::cerr << "Failed to write output, deactivating tracking" << std::endl;
            deactivate();
        }
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

void
Tracker::registerReferenceTrackingHooks() const noexcept
{
    compat::refTracerSetTracer(intercept::pyreftracer, nullptr);
}

void
Tracker::unregisterReferenceTrackingHooks() const noexcept
{
    compat::refTracerSetTracer(nullptr, nullptr);
}

std::unordered_set<PyObject*>
Tracker::getSurvivingObjects()
{
    std::scoped_lock<std::mutex> lock(*s_mutex);
    RecursionGuard guard;

    std::unordered_set<PyObject*> surviving_objects;
    // remove everything with 0 refcount
    for (auto obj : d_tracked_objects) {
#ifndef Py_GIL_DISABLED
        // CPython used to have some bugs where deallocation of objects
        // wasn't triggering the tracking hooks and that was causing us
        // to see deleted objects at this stage. This check is left here
        // as a precaution to know if CPython is still missing some cases
        // still. The check is not done in free-threaded builds because
        // the semantics of Py_REFCNT are more complicated and this may not
        // do what we want.
        if (Py_REFCNT(obj) == 0) {
            Py_UNREACHABLE();
        }
#endif
        Py_INCREF(obj);
        surviving_objects.insert(obj);
    }
    d_tracked_objects.clear();

    // While we hold s_mutex and our reference tracking hooks are installed,
    // other threads can't destroy any objects. As soon as we uninstall the
    // tracking hooks, objects can be destroyed by background threads without
    // us finding out. This means we can't uninstall the hooks until after
    // we've incremented the reference count of all the surviving objects.
    if (d_reference_tracking) {
        unregisterReferenceTrackingHooks();
    }
    return surviving_objects;
}

code_object_id_t
Tracker::registerCodeObject(PyCodeObject* code_ptr, const CodeObject& code_obj)
{
    auto it = d_code_object_cache.find(code_ptr);
    if (it != d_code_object_cache.end()) {
        return it->second;
    }

    // New code object - register it
    code_object_id_t code_id = d_next_code_object_id++;
    d_code_object_cache[code_ptr] = code_id;

    // Write the code object record
    pycode_map_val_t code_record{
            code_id,
            CodeObjectInfo{
                    code_obj.function_name,
                    code_obj.filename,
                    std::string(code_obj.linetable, code_obj.linetable_size),
                    code_obj.firstlineno}};

    if (!d_writer->writeRecord(code_record)) {
        std::cerr << "memray: Failed to write code object record, deactivating tracking" << std::endl;
        deactivate();
    }

    return code_id;
}

void
Tracker::forgetCodeObject(PyCodeObject* code)
{
    d_code_object_cache.erase(code);
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
Tracker::pushFrame(const Frame& cooked)
{
    const FramePush entry{cooked};
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
        bool trace_python_allocators,
        bool reference_tracking)
{
    s_instance_owner.reset(new Tracker(
            std::move(record_writer),
            native_traces,
            memory_interval,
            follow_fork,
            trace_python_allocators,
            reference_tracking));

    StopTheWorldGuard stop_the_world;
    std::unique_lock<std::mutex> lock(*s_mutex);
    PythonStackTracker::recordAllStacks(*s_instance_owner);
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

    PythonStackTracker::get().handleTraceEvent(what, frame);
    return 0;
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
set_up_pthread_fork_handlers()
{
    static std::once_flag once;
    call_once(once, [] {
        // On macOS the recursion guard uses pthread TLS keys, so we
        // need to create those keys before we install our handlers.
        RecursionGuard::initialize();
        pthread_atfork(&Tracker::prepareFork, &Tracker::parentFork, NULL);
    });
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

    PyEval_SetProfile(PyTraceFunction, nullptr);
    PythonStackTracker::get().populateShadowStack();
}

}  // namespace memray::tracking_api
