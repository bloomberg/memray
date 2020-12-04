#include <algorithm>
#include <list>
#include <malloc.h>
#include <mutex>

#include <Python.h>

#include "elf_shenanigans.h"
#include "guards.h"
#include "records.h"
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

thread_local frame_map_t Tracker::d_frames = frame_map_t();
std::atomic<Tracker*> Tracker::d_instance = nullptr;
std::ofstream Tracker::d_output = std::ofstream();
std::mutex Tracker::d_output_mutex;

Tracker::Tracker(const std::string& file_name)
{
    d_instance = this;
    d_output.open(file_name, std::ofstream::trunc);
    std::cout << "Opened " << file_name << " for writing" << std::endl;

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
Tracker::trackAllocation(void* ptr, size_t size, const char* func) const
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    AllocationRecord
            allocation_record{getpid(), gettid(), reinterpret_cast<unsigned long>(ptr), size, func};
    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << allocation_record;
    }
}

void
Tracker::trackDeallocation(void* ptr, const char* func) const
{
    if (RecursionGuard::isActive || !this->isActive()) {
        return;
    }
    RecursionGuard guard;
    AllocationRecord
            allocation_record{getpid(), gettid(), reinterpret_cast<unsigned long>(ptr), 0, func};
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
    d_frames.clear();
    std::list<frame_id_t> frame_ids;
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

        Frame frame({function, filename, lineno});
        frame_id_t id = add_frame(d_frames, frame);
        frame_ids.push_front(id);
        current_frame = current_frame->f_back;
    }

    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        for (const auto& frame_id : frame_ids) {
            d_output << frame_seq_pair_t{frame_id, FrameAction::PUSH};
        }
    }
}

void
Tracker::popFrame(const Frame& frame)
{
    frame_id_t frame_id = add_frame(d_frames, frame);

    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << frame_seq_pair_t{frame_id, FrameAction::POP};
    }
}

void
Tracker::addFrame(const Frame& frame)
{
    frame_id_t frame_id = add_frame(d_frames, frame);

    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output << frame_seq_pair_t{frame_id, FrameAction::PUSH};
    }
}

void
Tracker::activate()
{
    this->d_active = true;
    std::cout << "Activated" << std::endl;
}

void
Tracker::deactivate()
{
    d_active = false;
    {
        std::lock_guard<std::mutex> lock(d_output_mutex);
        d_output.flush();
    }
    std::cout << "Deactivated" << std::endl;
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
            Tracker::addFrame(Frame{function, filename, lineno});
            break;
        case PyTrace_RETURN: {
            // At the beggining of the tracking is possible that we don't
            // see some C functions (mainly from Cython) when pre-populating
            // the Tracker::frameStack() vector because the Python stack does
            // not "see" these C functions (the native stack does). This means
            // that is possible that we see the end of a function call that
            // was never in the vector. This is normal and the only thing we
            // need to do is to not remove anything from our vector.
            //
            // Notice that any further Cython call *will* be tracked because
            // the tracker function will be invoked with it and therefore we
            // will add it to the vector.
            // get previous frame
            Tracker::popFrame({function, filename, lineno});
            // FIXME
            //            const auto prev_frame_it = Tracker::frames().find(Tracker::lastFrameSeen());
            //            if (prev_frame_it != Tracker::frames().end()) {
            //                if (prev_frame_it->second.function_name == frame->f_code->co_filename) {
            //                    Tracker::popFrame({frame->f_code->co_name, frame->f_code->co_filename,
            //                    lineno});
            //                }
            //            }
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
