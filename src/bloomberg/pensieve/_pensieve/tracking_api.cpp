#include <algorithm>
#include <malloc.h>
#include <mutex>
#include <pthread.h>

#include <Python.h>

#include "elf_shenanigans.h"
#include "guards.h"
#include "records.h"
#include "tracking_api.h"

#include <sys/syscall.h>

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

frame_map_t Tracker::d_frames = frame_map_t();
std::atomic<Tracker*> Tracker::d_instance = nullptr;
std::ofstream Tracker::d_output = std::ofstream();
std::mutex Tracker::d_output_mutex;

Tracker::Tracker(const std::string& file_name)
{
    d_instance = this;
    d_output.open(file_name, std::ofstream::trunc);

    static std::once_flag once;
    call_once(once, [] { pthread_atfork(&prepare_fork, &parent_fork, &child_fork); });

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

    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << d_frames;
        d_output.close();
    }

    d_instance = nullptr;
}
void
Tracker::trackAllocation(void* ptr, size_t size, const hooks::Allocator func) const
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    RawAllocationRecord allocation_record{
            thread_id(),
            reinterpret_cast<unsigned long>(ptr),
            size,
            static_cast<int>(func)};

    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << allocation_record;
    }
}

void
Tracker::trackDeallocation(void* ptr, const hooks::Allocator func) const
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    RawAllocationRecord allocation_record{
            thread_id(),
            reinterpret_cast<unsigned long>(ptr),
            0,
            static_cast<int>(func)};
    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << allocation_record;
    }
}

void
Tracker::invalidate_module_cache()
{
    elf::overwrite_symbols();
}

void
Tracker::initializeFrameStack()
{
    std::vector<frame_id_t> frame_ids;
    PyFrameObject* current_frame = PyEval_GetFrame();
    thread_id_t tid = thread_id();
    while (current_frame != nullptr) {
        const char* function = PyUnicode_AsUTF8(current_frame->f_code->co_name);
        if (function == nullptr) {
            return;
        }
        const char* filename = PyUnicode_AsUTF8(current_frame->f_code->co_filename);
        if (filename == nullptr) {
            return;
        }
        unsigned long lineno = PyFrame_GetLineNumber(current_frame);

        Frame frame({function, filename, lineno});
        frame_id_t id = add_frame(d_frames, frame);
        frame_ids.push_back(id);
        current_frame = current_frame->f_back;
    }

    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        std::for_each(frame_ids.rbegin(), frame_ids.rend(), [&](auto& frame_id) {
            d_output << FrameSeqEntry{frame_id, tid, FrameAction::PUSH};
        });
    }
}

void
Tracker::popFrame(const Frame& frame)
{
    frame_id_t frame_id = add_frame(d_frames, frame);
    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << FrameSeqEntry{frame_id, thread_id(), FrameAction::POP};
    }
}

void
Tracker::addFrame(const Frame& frame)
{
    frame_id_t frame_id = add_frame(d_frames, frame);
    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << FrameSeqEntry{frame_id, thread_id(), FrameAction::PUSH};
    }
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
    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output.flush();
    }
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
    if (!function) {
        return -1;
    }
    const char* filename = PyUnicode_AsUTF8(frame->f_code->co_filename);
    if (!filename) {
        return -1;
    }
    unsigned long lineno = PyFrame_GetLineNumber(frame);
    switch (what) {
        case PyTrace_CALL:
            Tracker::addFrame(Frame{function, filename, lineno});
            break;
        case PyTrace_RETURN: {
            Tracker::popFrame({function, filename, lineno});
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
    Tracker::initializeFrameStack();
    PyEval_SetProfile(PyTraceFunction, PyLong_FromLong(123));
}

}  // namespace pensieve::tracking_api
