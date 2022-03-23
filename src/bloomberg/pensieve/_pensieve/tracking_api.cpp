#include <cassert>
#include <limits.h>
#include <link.h>
#include <mutex>
#include <unistd.h>
#include <utility>

#include <Python.h>

#include "exceptions.h"
#include "guards.h"
#include "hooks.h"
#include "record_writer.h"
#include "records.h"
#include "tracking_api.h"

using namespace pensieve::exception;
using namespace std::chrono_literals;

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
// To prevent that, we guard all accesses of the vector by first checking
// a bool that tells us whether the vector has been constructed and not yet
// destroyed. This bool is set from the constructor that creates the vector,
// and unset from the destructor that destroys the vector.
//
// This can result in the bool being constructed during thread teardown, but
// that doesn't cause the same problem because bool has a trivial destructor.
class PythonStackTracker
{
  private:
    struct LazilyEmittedFrame
    {
        PyFrameObject* frame;
        RawFrame raw_frame_record;
        bool emitted;
    };

    struct PythonStackTrackerState
    {
        std::vector<LazilyEmittedFrame> stack;

        PythonStackTrackerState()
        {
            const size_t INITIAL_PYTHON_STACK_FRAMES = 1024;
            stack.reserve(INITIAL_PYTHON_STACK_FRAMES);
            stack_constructed = true;
        }

        ~PythonStackTrackerState()
        {
            stack_constructed = false;
        }
    };

  public:
    static void reset(PyFrameObject* current_frame);
    static void emitPendingPops();
    static void emitPendingPushes();
    static int getCurrentPythonLineNumber();
    static void pushPythonFrame(
            PyFrameObject* frame,
            const char* function,
            const char* file_name,
            int parent_lineno);
    static void popPythonFrame();

  private:
    __attribute__((tls_model("local-dynamic"))) static thread_local uint32_t num_pending_pops;
    __attribute__((tls_model("local-dynamic"))) static thread_local PyFrameObject* entry_frame;
    __attribute__((tls_model("local-dynamic"))) static thread_local bool stack_constructed;
    __attribute__((tls_model("local-dynamic"))) static thread_local PythonStackTrackerState stack_holder;
};

__attribute__((tls_model("local-dynamic"))) thread_local uint32_t PythonStackTracker::num_pending_pops{};
__attribute__((tls_model("local-dynamic"))) thread_local PyFrameObject* PythonStackTracker::entry_frame{};
__attribute__((tls_model("local-dynamic"))) thread_local bool PythonStackTracker::stack_constructed{};
__attribute__((tls_model("local-dynamic"))) thread_local PythonStackTracker::PythonStackTrackerState PythonStackTracker::stack_holder{};

void
PythonStackTracker::reset(PyFrameObject* current_frame)
{
    entry_frame = current_frame;
    if (stack_constructed) {
        stack_holder.stack.clear();
    }
}

inline void
PythonStackTracker::emitPendingPops()
{
    Tracker::getTracker()->popFrames(num_pending_pops);
    num_pending_pops = 0;
}

void
PythonStackTracker::emitPendingPushes()
{
    if (!stack_constructed) {
        return;
    }

    auto last_emitted_rit =
            std::find_if(stack_holder.stack.rbegin(), stack_holder.stack.rend(), [](auto& f) {
                return f.emitted;
            });

    for (auto to_emit = last_emitted_rit.base(); to_emit != stack_holder.stack.end(); to_emit++) {
        if (!Tracker::getTracker()->pushFrame(to_emit->raw_frame_record)) {
            break;
        }
        to_emit->emitted = true;
    }
}

inline int
PythonStackTracker::getCurrentPythonLineNumber()
{
    assert(entry_frame == nullptr || Py_REFCNT(entry_frame) > 0);
    PyFrameObject* the_python_stack =
            (stack_constructed && !stack_holder.stack.empty() ? stack_holder.stack.back().frame
                                                              : entry_frame);
    return the_python_stack ? PyFrame_GetLineNumber(the_python_stack) : 0;
}

void
PythonStackTracker::pushPythonFrame(
        PyFrameObject* frame,
        const char* function,
        const char* filename,
        int parent_lineno)
{
    // Note: This will cause stack_constructed to become true if it isn't already.
    stack_holder.stack.push_back({frame, {function, filename, parent_lineno}, false});
}

void
PythonStackTracker::popPythonFrame()
{
    if (stack_constructed && !stack_holder.stack.empty()) {
        if (stack_holder.stack.back().emitted) {
            num_pending_pops += 1;
            assert(num_pending_pops != 0);  // Ensure we didn't overflow.
        }
        stack_holder.stack.pop_back();

        if (stack_holder.stack.empty()) {
            // Every frame we've pushed has been popped. Emit pending pops now
            // in case the thread is exiting and we don't get another chance.
            emitPendingPops();
        }
    } else {
        // If we have reached the top of the stack it means that we are returning
        // to frames that we never saw being pushed in the first place, so we need
        // to unset the entry frame to avoid incorrectly using it once is freed.
        entry_frame = nullptr;
    }
}

std::atomic<bool> Tracker::d_active = false;
std::atomic<Tracker*> Tracker::d_instance = nullptr;
__attribute__((tls_model("local-dynamic"))) thread_local size_t NativeTrace::MAX_SIZE{64};

Tracker::Tracker(
        std::unique_ptr<RecordWriter> record_writer,
        bool native_traces,
        unsigned int memory_interval)
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

    d_background_thread = std::make_unique<BackgroundThread>(d_writer, memory_interval);
    d_background_thread->start();

    tracking_api::Tracker::activate();
}

Tracker::~Tracker()
{
    RecursionGuard guard;
    tracking_api::Tracker::deactivate();
    d_background_thread->stop();
    PythonStackTracker::reset(nullptr);
    d_patcher.restore_symbols();
    d_writer->writeHeader(true);
    d_writer.reset();
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
            if (!d_writer->writeRecord(RecordType::MEMORY_RECORD, MemoryRecord{timeElapsed(), rss})) {
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
Tracker::trackAllocation(void* ptr, size_t size, const hooks::Allocator func)
{
    if (RecursionGuard::isActive || !Tracker::isActive()) {
        return;
    }
    RecursionGuard guard;
    int lineno = PythonStackTracker::getCurrentPythonLineNumber();

    PythonStackTracker::emitPendingPops();
    PythonStackTracker::emitPendingPushes();

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
    if (RecursionGuard::isActive || !Tracker::isActive()) {
        return;
    }
    RecursionGuard guard;
    int lineno = PythonStackTracker::getCurrentPythonLineNumber();

    PythonStackTracker::emitPendingPops();
    PythonStackTracker::emitPendingPushes();

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

void
Tracker::registerThreadName(const char* name)
{
    if (!d_writer->writeRecord(RecordType::THREAD_RECORD, ThreadRecord{thread_id(), name})) {
        std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
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

bool
Tracker::popFrames(uint32_t count)
{
    while (count) {
        uint8_t to_pop = (count > 255 ? 255 : count);
        count -= to_pop;

        const FramePop entry{thread_id(), to_pop};
        if (!d_writer->writeRecord(RecordType::FRAME_POP, entry)) {
            std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
            deactivate();
            return false;
        }
    }
    return true;
}

bool
Tracker::pushFrame(const RawFrame& frame)
{
    const frame_id_t frame_id = registerFrame(frame);
    const FramePush entry{frame_id, thread_id()};
    if (!d_writer->writeRecord(RecordType::FRAME_PUSH, entry)) {
        std::cerr << "pensieve: Failed to write output, deactivating tracking" << std::endl;
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

            int parent_lineno = PythonStackTracker::getCurrentPythonLineNumber();

            PythonStackTracker::pushPythonFrame(frame, function, filename, parent_lineno);
            break;
        }
        case PyTrace_RETURN: {
            PythonStackTracker::popPythonFrame();
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
    PythonStackTracker::reset(PyEval_GetFrame());
}

}  // namespace pensieve::tracking_api
