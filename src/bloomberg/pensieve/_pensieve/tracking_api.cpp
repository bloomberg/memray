#include <algorithm>
#include <malloc.h>
#include <mutex>

#include <Python.h>

#include "elf_shenanigans.h"
#include "guards.h"
#include "tracking_api.h"

#include <sys/syscall.h>
#define gettid() syscall(SYS_gettid)

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
}

}  // namespace

namespace pensieve::tracking_api {

// Tracker interface

thread_local std::vector<PyFrameRecord> Tracker::d_frame_stack = std::vector<PyFrameRecord>{};
Tracker* Tracker::d_instance = nullptr;

Tracker::Tracker()
: d_serializer(api::InMemorySerializer())
, d_record_writer(api::RecordWriter(d_serializer))
{
}

void
Tracker::trackAllocation(void* ptr, size_t size, const char* func)
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    std::vector<Frame> frames(d_frame_stack.begin(), d_frame_stack.end());
    AllocationRecord allocation_record{
            getpid(),
            gettid(),
            reinterpret_cast<unsigned long>(ptr),
            size,
            frames,
            func};
    d_record_writer.collect(allocation_record);
}

void
Tracker::trackDeallocation(void* ptr, const char* func)
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    std::vector<Frame> frames(d_frame_stack.begin(), d_frame_stack.end());
    AllocationRecord
            allocation_record{getpid(), gettid(), reinterpret_cast<unsigned long>(ptr), 0, frames, func};
    d_record_writer.collect(allocation_record);
}

void
Tracker::invalidate_module_cache()
{
    elf::overwrite_symbols();
}

const std::vector<PyFrameRecord>&
Tracker::frameStack()
{
    return d_frame_stack;
}

void
Tracker::initializeFrameStack()
{
    d_frame_stack.clear();
    PyFrameObject* current_frame = PyEval_GetFrame();
    while (current_frame != nullptr) {
        const char* function = PyUnicode_AsUTF8(current_frame->f_code->co_name);
        if (function == nullptr) {
            return;
        }
        const char* filename = PyUnicode_AsUTF8(current_frame->f_code->co_filename);
        if (filename == nullptr) {
            return;
        }
        int lineno = PyFrame_GetLineNumber(current_frame);
        d_frame_stack.emplace_back(PyFrameRecord{function, filename, lineno});
        current_frame = current_frame->f_back;
    }
    std::reverse(d_frame_stack.begin(), d_frame_stack.end());
}

void
Tracker::popFrame()
{
    if (!Tracker::d_frame_stack.empty()) {
        Tracker::d_frame_stack.pop_back();
    }
}

void
Tracker::addFrame(const PyFrameRecord&& frame)
{
    Tracker::d_frame_stack.emplace_back(frame);
}
void
Tracker::activate()
{
    this->d_active = true;
}
void
Tracker::deactivate()
{
    this->d_active = false;
}
const std::atomic<bool>&
Tracker::isActive() const
{
    return this->d_active;
}
Tracker*
Tracker::getTracker()
{
    return d_instance;
}

api::InMemorySerializer&
Tracker::getSerializer()
{
    return d_serializer;
}

api::RecordWriter&
Tracker::getRecordWriter()
{
    return d_record_writer;
}

const std::vector<AllocationRecord>&
Tracker::getAllocationRecords()
{
    d_record_writer.flush();
    return d_serializer.getRecords();
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
    const char* function = PyUnicode_AsUTF8(frame->f_code->co_name);
    if (!function) {
        return -1;
    }
    const char* filename = PyUnicode_AsUTF8(frame->f_code->co_filename);
    if (!filename) {
        return -1;
    }
    int lineno = PyFrame_GetLineNumber(frame);
    switch (what) {
        case PyTrace_CALL:
            Tracker::addFrame({function, filename, lineno});
            break;
        case PyTrace_RETURN:
            assert(function == Tracker::frameStack().back().function_name);
            Tracker::popFrame();
            break;
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
    Tracker::initializeFrameStack();
    PyEval_SetProfile(PyTraceFunction, PyLong_FromLong(123));
}

}  // namespace pensieve::tracking_api

namespace pensieve::api {

void
attach_init()
{
    static std::once_flag once;
    call_once(once, [] {
        pthread_atfork(&prepare_fork, &parent_fork, &child_fork);
        tracking_api::Tracker::d_instance = new tracking_api::Tracker();
    });
    assert(tracking_api::Tracker::getTracker());

    RecursionGuard guard;
    tracking_api::install_trace_function();
    tracking_api::Tracker::getTracker()->activate();
    elf::overwrite_symbols();
}
void
attach_fini()
{
    if (!(tracking_api::Tracker::getTracker() && tracking_api::Tracker::getTracker()->isActive())) {
        return;
    }

    RecursionGuard guard;
    tracking_api::Tracker::getTracker()->deactivate();
    elf::restore_symbols();
    tracking_api::Tracker::getTracker()->getRecordWriter().flush();
}
}  // namespace pensieve::api
