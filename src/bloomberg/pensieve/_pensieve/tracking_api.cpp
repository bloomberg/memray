#include <malloc.h>
#include <mutex>
#include <pthread.h>

#include <Python.h>

#include "elf_shenanigans.h"
#include "guards.h"
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
}

}  // namespace

namespace pensieve::tracking_api {

static inline thread_id_t
thread_id()
{
    return reinterpret_cast<thread_id_t>(pthread_self());
};

// Tracker interface

std::atomic<Tracker*> Tracker::d_instance = nullptr;
static thread_local PyFrameObject* current_frame = nullptr;

Tracker::Tracker(const std::string& file_name)
{
    d_instance = this;
    d_writer = std::make_unique<RecordWriter>(file_name);

    static std::once_flag once;
    call_once(once, [] { pthread_atfork(&prepare_fork, &parent_fork, &child_fork); });

    d_writer->writeHeader();

    RecursionGuard guard;
    tracking_api::install_trace_function();  //  TODO pass our instance here to avoid static object
    tracking_api::Tracker::getTracker()->activate();
    elf::overwrite_symbols();
}
Tracker::~Tracker()
{
    RecursionGuard guard;
    tracking_api::Tracker::getTracker()->deactivate();
    elf::restore_symbols();
    d_writer->writeHeader();
    d_writer.reset();
    d_instance = nullptr;
}
void
Tracker::trackAllocation(void* ptr, size_t size, const hooks::Allocator func) const
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    int lineno = current_frame ? PyCode_Addr2Line(current_frame->f_code, current_frame->f_lasti) : 0;
    AllocationRecord record{thread_id(), reinterpret_cast<unsigned long>(ptr), size, func, lineno};
    d_writer->writeRecord(RecordType::ALLOCATION, record);
}

void
Tracker::trackDeallocation(void* ptr, const hooks::Allocator func) const
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    int lineno = current_frame ? PyCode_Addr2Line(current_frame->f_code, current_frame->f_lasti) : 0;
    AllocationRecord record{thread_id(), reinterpret_cast<unsigned long>(ptr), 0, func, lineno};
    d_writer->writeRecord(RecordType::ALLOCATION, record);
}

void
Tracker::invalidate_module_cache()
{
    elf::overwrite_symbols();
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
    if (d_stack_size == 0) {
        return;
    }
    d_stack_size--;
    const frame_id_t frame_id = registerFrame(frame);
    const FrameSeqEntry entry{frame_id, thread_id(), FrameAction::POP};
    d_writer->writeRecord(RecordType::FRAME, entry);
}

void
Tracker::pushFrame(const RawFrame& frame)
{
    d_stack_size++;
    const frame_id_t frame_id = registerFrame(frame);
    const FrameSeqEntry entry{frame_id, thread_id(), FrameAction::PUSH};
    d_writer->writeRecord(RecordType::FRAME, entry);
}

void
Tracker::activate()
{
    this->d_active = true;
}

void
Tracker::deactivate()
{
    d_active = false;
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

// Trace Function interface

int
PyTraceFunction(
        [[maybe_unused]] PyObject* obj,
        PyFrameObject* frame,
        int what,
        [[maybe_unused]] PyObject* arg)
{
    RecursionGuard guard;
    if (!Tracker::getTracker()->isActive()) {
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
    int parent_lineno =
            current_frame ? PyCode_Addr2Line(current_frame->f_code, current_frame->f_lasti) : 0;
    switch (what) {
        case PyTrace_CALL:
            current_frame = frame;
            Tracker::getTracker()->pushFrame({function, filename, parent_lineno});
            break;
        case PyTrace_RETURN: {
            Tracker::getTracker()->popFrame({function, filename, parent_lineno});
            current_frame = frame->f_back;
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
    PyEval_SetProfile(PyTraceFunction, PyLong_FromLong(123));
}

}  // namespace pensieve::tracking_api
