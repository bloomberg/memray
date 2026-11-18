#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cassert>
#include <cerrno>
#include <cstring>
#include <stdio.h>

#ifdef __linux__
#    include <link.h>
#elif defined(__APPLE__)
#    include "macho_utils.h"
#    include <mach/mach.h>
#    include <mach/task.h>
#endif

#include <algorithm>
#include <mutex>
#include <unistd.h>

#include "capture_lifetime.h"
#include "compat.h"
#include "exceptions.h"
#include "greenlet_adapter.h"
#include "hooks.h"
#include "python_stack_capture.h"
#include "record_writer.h"
#include "records.h"
#include "tracking_api.h"

using namespace memray::exception;
using namespace std::chrono_literals;

namespace {

static std::string
copyUnicodeRaw(PyObject* object)
{
    // Read the immutable canonical Unicode data. Do not create a UTF-8 cache.
    auto* ascii = reinterpret_cast<PyASCIIObject*>(object);
    const int kind = ascii->state.kind;
    const void* data = ascii->state.compact
                               ? static_cast<void*>(
                                         reinterpret_cast<char*>(object)
                                         + (ascii->state.ascii ? sizeof(PyASCIIObject)
                                                               : sizeof(PyCompactUnicodeObject)))
                               : reinterpret_cast<PyUnicodeObject*>(object)->data.any;
    if (ascii->state.ascii) {
        return std::string(static_cast<const char*>(data), ascii->length);
    }
    std::string result;
    result.reserve(ascii->length);
    for (Py_ssize_t i = 0; i < ascii->length; ++i) {
        uint32_t cp = kind == 1   ? static_cast<const uint8_t*>(data)[i]
                      : kind == 2 ? static_cast<const uint16_t*>(data)[i]
                                  : static_cast<const uint32_t*>(data)[i];
        if (cp < 0x80) {
            result.push_back(cp);
        } else if (cp < 0x800) {
            result.push_back(0xc0 | (cp >> 6));
            result.push_back(0x80 | (cp & 0x3f));
        } else if (cp < 0x10000) {
            result.push_back(0xe0 | (cp >> 12));
            result.push_back(0x80 | ((cp >> 6) & 0x3f));
            result.push_back(0x80 | (cp & 0x3f));
        } else {
            result.push_back(0xf0 | (cp >> 18));
            result.push_back(0x80 | ((cp >> 12) & 0x3f));
            result.push_back(0x80 | ((cp >> 6) & 0x3f));
            result.push_back(0x80 | (cp & 0x3f));
        }
    }
    return result;
}

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
starts_with(const std::string_view& haystack, const std::string_view& needle)
{
    return haystack.compare(0, needle.size(), needle) == 0;
}

static bool
parse_proc_status_value_in_kb(
        const std::string& proc_status,
        const std::string_view& field_name,
        size_t* value_in_kb)
{
    size_t line_start = 0;
    while (line_start < proc_status.size()) {
        size_t line_end = proc_status.find('\n', line_start);
        if (line_end == std::string::npos) {
            line_end = proc_status.size();
        }

        std::string_view line = std::string_view(proc_status).substr(line_start, line_end - line_start);
        if (starts_with(line, field_name)
            && sscanf(proc_status.c_str() + line_start + field_name.size(), "%zu kB", value_in_kb) == 1)
        {
            return true;
        }

        line_start = line_end + 1;
    }
    return false;
}
#endif

}  // namespace

namespace memray::tracking_api {

bool
getRSSFromProcStatus(const std::string& proc_status, size_t* rss_in_bytes)
{
#ifdef __linux__
    size_t rss_in_kb;
    if (!parse_proc_status_value_in_kb(proc_status, "VmRSS:", &rss_in_kb)) {
        return false;
    }

    size_t hugetlb_in_kb;
    if (parse_proc_status_value_in_kb(proc_status, "HugetlbPages:", &hugetlb_in_kb)) {
        rss_in_kb += hugetlb_in_kb;
    }

    *rss_in_bytes = rss_in_kb * 1024;
    return true;
#else
    return false;
#endif
}

#ifdef __linux__
MEMRAY_FAST_TLS thread_local bool RecursionGuard::_isActive = false;
#else
pthread_key_t RecursionGuard::isActiveKey;
#endif

thread_id_t
allocateThreadId()
{
    static std::atomic<thread_id_t> s_tid_counter = 0;
    return ++s_tid_counter;
}

MEMRAY_FAST_TLS thread_local thread_id_t t_native_tid = allocateThreadId();
MEMRAY_FAST_TLS thread_local thread_id_t t_tid = t_native_tid;

static inline thread_id_t
thread_id()
{
    return t_tid;
}

static void
updateLogicalThread(Tracker& tracker, uintptr_t identity)
{
    const thread_id_t next = identity ? identity : t_native_tid;
    if (next != t_tid) {
        python_stack_capture::clear(tracker);
        t_tid = next;
    }
}

// Tracker interface

std::unique_ptr<TrackerMutex> Tracker::s_mutex(new TrackerMutex);
pthread_key_t Tracker::s_native_unwind_vector_key;
std::unique_ptr<Tracker> Tracker::s_instance_owner;
std::atomic<Tracker*> Tracker::s_instance = nullptr;
std::atomic<uint64_t> Tracker::s_session_generation{0};
std::atomic<bool> Tracker::s_native_traces{false};

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
        if (0
            != pthread_key_create(
                    &s_native_unwind_vector_key,
                    [](void* data) { delete static_cast<std::vector<NativeTrace::ip_t>*>(data); }))
        {
            throw std::runtime_error{"Failed to create pthread key"};
        }

        try {
            hooks::ensureAllHooksAreValid();
            NativeTrace::setup();

#if PY_VERSION_HEX >= 0x030C0000
            const int watcher = PyCode_AddWatcher([](PyCodeEvent event, PyCodeObject* code) {
                if (event == PY_CODE_EVENT_DESTROY) {
                    Tracker::codeObjectDestroyed(code);
                }
                return 0;
            });
            if (watcher < 0) {
                PyErr_Clear();
                throw std::runtime_error("Cannot track code lifetimes: no code watcher slots available");
            }
#endif
        } catch (...) {
            pthread_key_delete(s_native_unwind_vector_key);
            throw;
        }
    });

    bool lifetime_active = false;
    bool identity_active = false;
    bool reference_hooks_active = false;
    bool pymalloc_hooks_active = false;
    try {
        hooks::ensureArrowHooksAreValid();
        python_stack_capture::initialize();
        {
            RecursionGuard guard;
            compat::withStoppedWorld([&] {
                capture_lifetime::activate();
                lifetime_active = true;
                greenlet_adapter::beginTracking();
                identity_active = true;
                const auto identity = greenlet_adapter::currentIdentity();
                t_tid = identity ? identity : t_native_tid;
            });
        }

        d_writer->setMainTidAndSkippedFrames(thread_id(), computeMainTidSkip());
        if (!d_writer->writeHeader(false)) {
            throw IoError{"Failed to write output header: " + std::string(strerror(errno))};
        }

        RecursionGuard guard;
        updateModuleCacheImpl();

        if (d_reference_tracking) {
            registerReferenceTrackingHooks();
            reference_hooks_active = true;
        }
        if (d_trace_python_allocators) {
            compat::withStoppedWorld([&] {
                registerPymallocHooks();
                pymalloc_hooks_active = true;
            });
        }
        d_background_thread = std::make_unique<BackgroundThread>(d_writer, memory_interval);
        d_background_thread->start();

        d_patcher.overwrite_symbols();
    } catch (...) {
        RecursionGuard guard;
        if (d_background_thread) {
            d_background_thread->stop();
        }
        {
            std::scoped_lock<TrackerMutex> lock(*s_mutex);
            d_patcher.restore_symbols();
        }
        if (reference_hooks_active) {
            unregisterReferenceTrackingHooks();
        }
        compat::withStoppedWorld([&] {
            if (pymalloc_hooks_active) {
                unregisterPymallocHooks();
            }
            if (lifetime_active) {
                capture_lifetime::deactivate();
            }
            if (identity_active) {
                greenlet_adapter::endTracking();
            }
        });
        throw;
    }
}

Tracker::~Tracker()
{
    RecursionGuard guard;
    tracking_api::Tracker::deactivate();

    d_background_thread->stop();

    {
        std::scoped_lock lock(*s_mutex);
        d_patcher.restore_symbols();
    }

    if (Py_IsInitialized() && !compat::isPythonFinalizing()) {
        PyGILState_STATE gstate;
        gstate = PyGILState_Ensure();

        if (d_reference_tracking) {
            std::scoped_lock lock(*s_mutex);
            unregisterReferenceTrackingHooks();
        }

        compat::withStoppedWorld([&] {
            if (d_trace_python_allocators) {
                std::scoped_lock<TrackerMutex> lock(*s_mutex);
                unregisterPymallocHooks();
            }
            capture_lifetime::deactivate();
            greenlet_adapter::endTracking();
        });

        PyGILState_Release(gstate);
    }

    std::scoped_lock lock(*s_mutex);
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
    d_procs_statm.open("/proc/self/status");
    if (!d_procs_statm) {
        throw IoError{"Failed to open /proc/self/status: " + std::string(strerror(errno))};
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
    std::string proc_status{
            std::istreambuf_iterator<char>(d_procs_statm),
            std::istreambuf_iterator<char>()};
    d_procs_statm.clear();
    d_procs_statm.seekg(0);

    size_t rss_in_bytes;
    if (!getRSSFromProcStatus(proc_status, &rss_in_bytes)) {
        std::cerr << "WARNING: Failed to read RSS value from /proc/self/status" << std::endl;
        d_procs_statm.close();
        return 0;
    }

    return rss_in_bytes;
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

    std::lock_guard lock(*s_mutex);
    if (!d_writer->writeRecord(MemoryRecord{now, rss})) {
        if (Tracker::isActive()) {
            std::cerr << "Failed to write output, deactivating tracking" << std::endl;
            Tracker::deactivate();
        }
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
                std::unique_lock lock(d_mutex);
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
        std::scoped_lock lock(d_mutex);
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
    // Don't do any custom track_allocation handling while inside fork.
    RecursionGuard::setValue(true);
}

void
Tracker::parentFork()
{
    // We can continue tracking.
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
    s_mutex.reset(new TrackerMutex);

    // Save a reference to the old tracker (if any), then unset our singleton.
    Tracker* old_tracker = s_instance;
    Tracker::deactivate();

    if (old_tracker && old_tracker->d_trace_python_allocators) {
        old_tracker->unregisterPymallocHooks();
    }
    capture_lifetime::deactivate();
    greenlet_adapter::endTracking();

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

    compat::withStoppedWorld([&] {
        std::unique_lock<TrackerMutex> lock(*s_mutex);
        python_stack_capture::beginTracking(s_instance_owner->d_unwind_native_frames);
        tracking_api::Tracker::activate();
    });
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
        const int flags = compat::frameGetCode(frame)->co_flags;
        if (flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR)) {
            // A resumable frame can detach its caller chain after startup.
            // A fixed trim count can then hide live application frames.
            return 0;
        }
        ++num_frames;
        frame = compat::frameGetBack(frame);
    }

    assert(num_frames > 0);
    return num_frames - 1;
}

void
Tracker::trackAllocationImpl(
        void* ptr,
        size_t size,
        hooks::Allocator func,
        const std::optional<NativeTrace>& trace,
        uintptr_t identity)
{
    updateLogicalThread(*this, identity);
    registerCachedThreadName();
    python_stack_capture::emit(*this);

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
Tracker::trackDeallocationImpl(void* ptr, size_t size, hooks::Allocator func, uintptr_t identity)
{
    updateLogicalThread(*this, identity);
    registerCachedThreadName();
    AllocationRecord record{reinterpret_cast<uintptr_t>(ptr), size, func};
    if (!d_writer->writeThreadSpecificRecord(thread_id(), record)) {
        std::cerr << "Failed to write output, deactivating tracking" << std::endl;
        deactivate();
    }
}

void
Tracker::trackObjectImpl(
        PyObject* obj,
        int event,
        const std::optional<NativeTrace>& trace,
        uintptr_t identity)
{
    updateLogicalThread(*this, identity);
    registerCachedThreadName();
    python_stack_capture::emit(*this);

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
    // libarrow can be loaded after tracking starts.
    hooks::ensureArrowHooksAreValid();
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
    std::scoped_lock lock(*s_mutex);
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
Tracker::registerCodeObject(PyCodeObject* code_ptr)
{
    auto it = d_code_object_cache.find(code_ptr);
    if (it != d_code_object_cache.end()) {
        return it->second;
    }
    auto name = copyUnicodeRaw(code_ptr->co_name);
    auto filename = copyUnicodeRaw(code_ptr->co_filename);
#if PY_VERSION_HEX >= 0x030A0000
    auto* linetable = reinterpret_cast<PyBytesObject*>(code_ptr->co_linetable);
#else
    auto* linetable = reinterpret_cast<PyBytesObject*>(code_ptr->co_lnotab);
#endif
    const auto code_id = d_next_code_object_id++;
    d_code_object_cache[code_ptr] = code_id;
    // Names historically stop at the first NUL.
    name.resize(std::strlen(name.c_str()));
    filename.resize(std::strlen(filename.c_str()));
    pycode_map_val_t code_record{
            code_id,
            CodeObjectInfo{
                    std::move(name),
                    std::move(filename),
                    std::string(linetable->ob_sval, linetable->ob_base.ob_size),
                    code_ptr->co_firstlineno}};
    if (!d_writer->writeRecord(code_record)) {
        std::cerr << "memray: Failed to write code object record, deactivating tracking" << std::endl;
        deactivate();
    }
    return code_id;
}

void
Tracker::refreshRawCodeCache(uint64_t generation)
{
    if (d_raw_code_generation != generation) {
        d_code_object_cache.clear();
        d_raw_code_generation = generation;
    }
}

void
Tracker::codeObjectDestroyed(PyCodeObject* code)
{
    python_stack_capture::forgetTlbcCode();
    if (!Tracker::isActive()) {
        return;
    }
    if (RecursionGuard::isActive()) {
        python_stack_capture::invalidateCodeCache();
        return;
    }
    RecursionGuard guard;
    std::unique_lock<TrackerMutex> lock(*s_mutex);
    if (auto* tracker = Tracker::getTracker()) {
        tracker->d_code_object_cache.erase(code);
    }
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
    s_native_traces.store(s_instance_owner->d_unwind_native_frames, std::memory_order_release);
    s_session_generation.fetch_add(1, std::memory_order_release);
    s_instance = s_instance_owner.get();
}

void
Tracker::deactivate()
{
    s_instance = nullptr;
    s_session_generation.fetch_add(1, std::memory_order_release);
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

    RecursionGuard guard;
    compat::withStoppedWorld([&] {
        std::unique_lock<TrackerMutex> lock(*s_mutex);
        python_stack_capture::beginTracking(s_instance_owner->d_unwind_native_frames);
        tracking_api::Tracker::activate();
    });
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

void
set_up_pthread_fork_handlers()
{
    static std::once_flag once;
    call_once(once, [] {
        // On macOS the recursion guard uses pthread TLS keys, so we
        // need to create those keys before we install our handlers.
        RecursionGuard::initialize();
        pthread_atfork(&Tracker::prepareFork, &Tracker::parentFork, [] {
            greenlet_adapter::childFork();
            capture_lifetime::childFork();
        });
    });
}

}  // namespace memray::tracking_api
