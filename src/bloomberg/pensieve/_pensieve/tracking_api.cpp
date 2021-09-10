#include <cassert>
#include <limits.h>
#include <link.h>
#include <mutex>
#include <unistd.h>

#include <Python.h>
#include <sys/file.h>

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

std::atomic<bool> Tracker::d_active = false;
std::atomic<Tracker*> Tracker::d_instance = nullptr;
static thread_local PyFrameObject* entry_frame = nullptr;
static thread_local PyFrameObject* current_frame = nullptr;
static thread_local std::vector<PyFrameObject*> python_stack{};
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
    python_stack.clear();
    d_patcher.restore_symbols();
    // FIXME Avoid trying to seek in the output. The only thing we have to write at the end is the
    // tracking stats. We should do this as a separate footer record type.
    //    d_writer->writeHeader();
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
    try {
        d_writer->writeRecord(RecordType::ALLOCATION, record);
    } catch (const IoError&) {
        std::cerr << "Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
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
    try {
        d_writer->writeRecord(RecordType::ALLOCATION, record);
    } catch (const IoError&) {
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
        return 1;
    }

    for (const auto& segment : segments) {
        try {
            if (!writer->writeRecordUnsafe(RecordType::SEGMENT, segment)) {
                return 1;
            }
        } catch (const IoError&) {
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
    try {
        d_writer->writeSimpleType(RecordType::MEMORY_MAP_START);
    } catch (const IoError&) {
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
        pyframe_map_val_t frame_index{
                frame_id,
                Frame{frame.function_name, frame.filename, frame.parent_lineno}};
        try {
            d_writer->writeRecord(RecordType::FRAME_INDEX, frame_index);
        } catch (const IoError&) {
            std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
            deactivate();
        }
    }
    return frame_id;
}

void
Tracker::popFrame(const RawFrame& frame)
{
    const frame_id_t frame_id = registerFrame(frame);
    const FrameSeqEntry entry{frame_id, thread_id(), FrameAction::POP};
    try {
        d_writer->writeRecord(RecordType::FRAME, entry);
    } catch (const IoError&) {
        std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::pushFrame(const RawFrame& frame)
{
    const frame_id_t frame_id = registerFrame(frame);
    const FrameSeqEntry entry{frame_id, thread_id(), FrameAction::PUSH};
    try {
        d_writer->writeRecord(RecordType::FRAME, entry);
    } catch (const IoError&) {
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
            } else {
                // If we have reached the top of the stack it means that we are returning
                // to frames that we never saw being pushed in the first place, so we need
                // to unset the entry frame to avoid incorrectly using it once is freed.
                entry_frame = nullptr;
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
