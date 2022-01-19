#include <cassert>
#include <limits.h>
#include <link.h>
#include <mutex>
#include <unistd.h>

#include <Python.h>

#include "exceptions.h"
#include "guards.h"
#include "hooks.h"
#include "record_writer.h"
#include "records.h"
#include "tracking_api.h"

using namespace pensieve::exception;

namespace {
void

prepare_fork()
{
    // Don't do any custom track_allocation handling while inside fork
    RecursionGuard::isActive = true;
}

void
parent_fork()
{
    // We can continue tracking
    RecursionGuard::isActive = false;
}

void
child_fork()
{
    // TODO: allow children to be tracked
    RecursionGuard::isActive = true;
    pensieve::tracking_api::Tracker::getTracker()->deactivate();
}

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

}  // namespace

namespace pensieve::tracking_api {

static inline thread_id_t
thread_id()
{
    return reinterpret_cast<thread_id_t>(pthread_self());
};

// Tracker interface

static const size_t INITIAL_PYTHON_STACK_FRAMES = 1024;

static thread_local bool python_stack_constructed = false;

struct PythonStackTracker
{
    std::vector<PyFrameObject*> stack;

    PythonStackTracker()
    {
        stack.reserve(INITIAL_PYTHON_STACK_FRAMES);
        python_stack_constructed = true;
    }

    ~PythonStackTracker()
    {
        python_stack_constructed = false;
    }
};

std::atomic<bool> Tracker::d_active = false;
std::atomic<Tracker*> Tracker::d_instance = nullptr;
static thread_local PyFrameObject* entry_frame = nullptr;
static thread_local PyFrameObject* current_frame = nullptr;
static thread_local PythonStackTracker python_stack_tracker{};
thread_local size_t NativeTrace::MAX_SIZE{64};

static inline int
getCurrentPythonLineNumber()
{
    assert(entry_frame == nullptr || Py_REFCNT(entry_frame) > 0);
    PyFrameObject* the_python_stack = current_frame ? current_frame : entry_frame;
    return the_python_stack ? PyFrame_GetLineNumber(the_python_stack) : 0;
}

Tracker::Tracker(std::unique_ptr<RecordWriter> record_writer, bool native_traces)
: d_writer(std::move(record_writer))
, d_unwind_native_frames(native_traces)
{
    d_instance = this;

    static std::once_flag once;
    call_once(once, [] {
        hooks::ensureAllHooksAreValid();
        pthread_atfork(&prepare_fork, &parent_fork, &child_fork);
        NativeTrace::setup();
    });

    if (!d_writer->writeHeader(false)) {
        throw IoError{"Failed to write output header"};
    }
    updateModuleCache();

    RecursionGuard guard;
    tracking_api::install_trace_function();  //  TODO pass our instance here to avoid static object
    d_patcher.overwrite_symbols();
    tracking_api::Tracker::activate();
}
Tracker::~Tracker()
{
    RecursionGuard guard;
    tracking_api::Tracker::deactivate();
    if (python_stack_constructed) {
        python_stack_tracker.stack.clear();
    }
    d_patcher.restore_symbols();
    d_writer->writeHeader(true);
    d_writer.reset();
    d_instance = nullptr;
}
void
Tracker::trackAllocation(void* ptr, size_t size, const hooks::Allocator func)
{
    // IMPORTANT!
    // If a TLS variable has not been constructed, accessing it will cause it
    // to be constructed. That's normally great, but we need to prevent that
    // from happening for `python_stack_tracker` in this function.
    //
    // This function can get called when libc and libpthread are allocating or
    // deallocating the memory owned by thread local variables, which can
    // happen before `python_stack_tracker` has been constructed for the
    // thread, or after it has already been destroyed. If it has already been
    // destroyed and we access it, libpthread will construct a new vector for
    // `python_stack_tracker.stack`, and register the destructor to be called
    // later, and then go on to free the memory that the vector was just
    // constructed into without calling the destructor. Later on, the
    // destructor will fire and try to destroy already-freed memory as though
    // it is still a vector, most likely causing heap corruption.
    //
    // To prevent this, we track if `python_stack_tracker` already exists for
    // a thread using the POD TLS variable `python_stack_constructed`. We set
    // that TLS variable from the `python_stack_tracker` constructor when the
    // vector is created, and unset it from the destructor. We avoid accessing
    // `python_stack_tracker` unless that variable is set, to avoid ever lazily
    // creating the vector inside this function or any function it calls.
    //
    // This approach can result in the `bool` being lazily constructed, but
    // that doesn't cause the same problem because it has a trivial destructor.
    if (RecursionGuard::isActive || !Tracker::isActive()) {
        return;
    }
    RecursionGuard guard;
    int lineno = getCurrentPythonLineNumber();

    size_t native_index = 0;
    if (d_unwind_native_frames) {
        NativeTrace trace;
        // Skip the internal frames so we don't need to filter them later.
        if (trace.fill(2)) {
            native_index = d_native_trace_tree.getTraceIndex(trace, [&](frame_id_t ip, uint32_t index) {
                return d_writer->writeRecord(
                        RecordType::NATIVE_TRACE_INDEX,
                        UnresolvedNativeFrame{ip, index});
            });
        }
    }

    AllocationRecord
            record{thread_id(), reinterpret_cast<uintptr_t>(ptr), size, func, lineno, native_index};
    if (!d_writer->writeRecord(RecordType::ALLOCATION, record)) {
        std::cerr << "Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::trackDeallocation(void* ptr, size_t size, const hooks::Allocator func)
{
    // IMPORTANT!
    // If a TLS variable has not been constructed, accessing it will cause it
    // to be constructed. That's normally great, but we need to prevent that
    // from happening for `python_stack_tracker` in this function.
    //
    // This function can get called when libc and libpthread are allocating or
    // deallocating the memory owned by thread local variables, which can
    // happen before `python_stack_tracker` has been constructed for the
    // thread, or after it has already been destroyed. If it has already been
    // destroyed and we access it, libpthread will construct a new vector for
    // `python_stack_tracker.stack`, and register the destructor to be called
    // later, and then go on to free the memory that the vector was just
    // constructed into without calling the destructor. Later on, the
    // destructor will fire and try to destroy already-freed memory as though
    // it is still a vector, most likely causing heap corruption.
    //
    // To prevent this, we track if `python_stack_tracker` already exists for
    // a thread using the POD TLS variable `python_stack_constructed`. We set
    // that TLS variable from the `python_stack_tracker` constructor when the
    // vector is created, and unset it from the destructor. We avoid accessing
    // `python_stack_tracker` unless that variable is set, to avoid ever lazily
    // creating the vector inside this function or any function it calls.
    //
    // This approach can result in the `bool` being lazily constructed, but
    // that doesn't cause the same problem because it has a trivial destructor.
    if (RecursionGuard::isActive || !Tracker::isActive()) {
        return;
    }
    RecursionGuard guard;
    int lineno = getCurrentPythonLineNumber();
    AllocationRecord record{thread_id(), reinterpret_cast<uintptr_t>(ptr), size, func, lineno, 0};
    if (!d_writer->writeRecord(RecordType::ALLOCATION, record)) {
        std::cerr << "Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::invalidate_module_cache()
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

    if (!writer->writeRecordUnsafe(
                RecordType::SEGMENT_HEADER,
                SegmentHeader{filename, segments.size(), info->dlpi_addr}))
    {
        std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
        Tracker::deactivate();
        return 1;
    }

    for (const auto& segment : segments) {
        if (!writer->writeRecordUnsafe(RecordType::SEGMENT, segment)) {
            std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
            Tracker::deactivate();
            return 1;
        }
    }

    return 0;
}

void
Tracker::updateModuleCache()
{
    if (!d_unwind_native_frames) {
        return;
    }
    auto writer_lock = d_writer->acquireLock();
    if (!d_writer->writeSimpleType(RecordType::MEMORY_MAP_START)) {
        std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }

    dl_iterate_phdr(&dl_iterate_phdr_callback, d_writer.get());
}

frame_id_t
Tracker::registerFrame(const RawFrame& frame)
{
    const auto [frame_id, is_new_frame] = d_frames.getIndex(frame);
    if (is_new_frame) {
        pyrawframe_map_val_t frame_index{frame_id, frame};
        if (!d_writer->writeRecord(RecordType::FRAME_INDEX, frame_index)) {
            std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
            deactivate();
        }
    }
    return frame_id;
}

void
Tracker::popFrame()
{
    const FramePop entry{thread_id()};
    if (!d_writer->writeRecord(RecordType::FRAME_POP, entry)) {
        std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::pushFrame(const RawFrame& frame)
{
    const frame_id_t frame_id = registerFrame(frame);
    const FramePush entry{frame_id, thread_id()};
    if (!d_writer->writeRecord(RecordType::FRAME_PUSH, entry)) {
        std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
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

Tracker*
Tracker::getTracker()
{
    return d_instance;
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
            const char* function = PyUnicode_AsUTF8(frame->f_code->co_name);
            if (function == nullptr) {
                return -1;
            }

            const char* filename = PyUnicode_AsUTF8(frame->f_code->co_filename);
            if (filename == nullptr) {
                return -1;
            }

            int parent_lineno = getCurrentPythonLineNumber();

            current_frame = frame;
            python_stack_tracker.stack.push_back(frame);
            Tracker::getTracker()->pushFrame({function, filename, parent_lineno});
            break;
        }
        case PyTrace_RETURN: {
            if (!python_stack_tracker.stack.empty()) {
                Tracker::getTracker()->popFrame();
                python_stack_tracker.stack.pop_back();
            } else {
                // If we have reached the top of the stack it means that we are returning
                // to frames that we never saw being pushed in the first place, so we need
                // to unset the entry frame to avoid incorrectly using it once is freed.
                entry_frame = nullptr;
            }
            current_frame = python_stack_tracker.stack.empty() ? nullptr : python_stack_tracker.stack.back();
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
    entry_frame = PyEval_GetFrame();
    current_frame = nullptr;
    python_stack_tracker.stack.clear();
}

}  // namespace pensieve::tracking_api
