#include <cassert>
#include <limits.h>
#include <link.h>
#include <mutex>
#include <unistd.h>

#include <Python.h>

#include "guards.h"
#include "hooks.h"
#include "record_writer.h"
#include "records.h"
#include "tracking_api.h"

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

std::atomic<bool> Tracker::d_active = false;
std::atomic<Tracker*> Tracker::d_instance = nullptr;
static thread_local PyFrameObject* entry_frame = nullptr;
static thread_local PyFrameObject* current_frame = nullptr;
static thread_local std::vector<PyFrameObject*> python_stack{};
thread_local size_t NativeTrace::MAX_SIZE{64};

static inline int
getCurrentPythonLineNumber()
{
    const PyFrameObject* the_python_stack = current_frame ? current_frame : entry_frame;
    return the_python_stack ? PyCode_Addr2Line(the_python_stack->f_code, the_python_stack->f_lasti) : 0;
}

Tracker::Tracker(const std::string& file_name, bool native_traces, const std::string& command_line)
: d_unwind_native_frames(native_traces)
{
    d_instance = this;
    d_writer = std::make_unique<RecordWriter>(file_name, command_line, native_traces);

    static std::once_flag once;
    call_once(once, [] {
        hooks::ensureAllHooksAreValid();
        pthread_atfork(&prepare_fork, &parent_fork, &child_fork);
        NativeTrace::setup();
        python_stack.reserve(INITIAL_PYTHON_STACK_FRAMES);
    });

    d_writer->writeHeader();
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
    d_patcher.restore_symbols();
    d_writer->writeHeader();
    d_writer.reset();
    d_instance = nullptr;
}
void
Tracker::trackAllocation(void* ptr, size_t size, const hooks::Allocator func)
{
    // IMPORTANT!
    // This function can get called when libc and libpthread are deallocating
    // the memory associated by threads and thread local storage variables so it's
    // important that no TLS variables with non-trivial destructors are used in this
    // function or any function called from here.

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
    d_writer->writeRecord(RecordType::ALLOCATION, record);
}

void
Tracker::trackDeallocation(void* ptr, size_t size, const hooks::Allocator func)
{
    // IMPORTANT!
    // This function can get called when libc and libpthread are deallocating
    // the memory associated by threads and thread local storage variables so it's
    // important that no TLS variables with non-trivial destructors are used in this
    // function or any function called from here.

    if (RecursionGuard::isActive || !Tracker::isActive()) {
        return;
    }
    RecursionGuard guard;
    int lineno = getCurrentPythonLineNumber();
    AllocationRecord record{thread_id(), reinterpret_cast<uintptr_t>(ptr), size, func, lineno, 0};
    d_writer->writeRecord(RecordType::ALLOCATION, record);
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
        return 1;
    }

    for (const auto& segment : segments) {
        if (!writer->writeRecordUnsafe(RecordType::SEGMENT, segment)) {
            return 1;
        }
    }

    return 0;
}

void
Tracker::updateModuleCache()
{
    auto writer_lock = d_writer->acquireLock();
    d_writer->writeSimpleType(RecordType::MEMORY_MAP_START);
    dl_iterate_phdr(&dl_iterate_phdr_callback, d_writer.get());
}

frame_id_t
Tracker::registerFrame(const RawFrame& frame)
{
    const auto [frame_id, is_new_frame] = d_frames.getIndex(frame);
    if (is_new_frame) {
        pyframe_map_val_t frame_index{
                frame_id,
                Frame{frame.function_name, frame.filename, frame.parent_lineno}};
        d_writer->writeRecord(RecordType::FRAME_INDEX, frame_index);
    }
    return frame_id;
}

void
Tracker::popFrame(const RawFrame& frame)
{
    const frame_id_t frame_id = registerFrame(frame);
    const FrameSeqEntry entry{frame_id, thread_id(), FrameAction::POP};
    d_writer->writeRecord(RecordType::FRAME, entry);
}

void
Tracker::pushFrame(const RawFrame& frame)
{
    const frame_id_t frame_id = registerFrame(frame);
    const FrameSeqEntry entry{frame_id, thread_id(), FrameAction::PUSH};
    d_writer->writeRecord(RecordType::FRAME, entry);
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

    const char* function = PyUnicode_AsUTF8(frame->f_code->co_name);
    if (function == nullptr) {
        return -1;
    }
    const char* filename = PyUnicode_AsUTF8(frame->f_code->co_filename);
    if (filename == nullptr) {
        return -1;
    }
    int parent_lineno = getCurrentPythonLineNumber();
    switch (what) {
        case PyTrace_CALL:
            current_frame = frame;
            python_stack.push_back(frame);
            Tracker::getTracker()->pushFrame({function, filename, parent_lineno});
            break;
        case PyTrace_RETURN: {
            if (!python_stack.empty()) {
                Tracker::getTracker()->popFrame({function, filename, parent_lineno});
                python_stack.pop_back();
            }
            current_frame = python_stack.empty() ? nullptr : python_stack.back();
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
    python_stack.clear();
}

}  // namespace pensieve::tracking_api
