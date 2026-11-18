#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <frameobject.h>
#if PY_VERSION_HEX >= 0x030E0000
#    include <opcode.h>
#endif

#ifdef _PyGC_FINALIZED
#    undef _PyGC_FINALIZED
#endif
#define Py_BUILD_CORE
#if PY_VERSION_HEX < 0x030D0000
#    undef HAVE_STD_ATOMIC
#endif
#if PY_VERSION_HEX >= 0x030E0000
#    include <internal/pycore_frame.h>
#    include <internal/pycore_interp_structs.h>
#    include <internal/pycore_interpframe_structs.h>
#elif PY_VERSION_HEX >= 0x030B0000
#    include <internal/pycore_frame.h>
#endif
#include <internal/pycore_runtime.h>
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
#    include <internal/pycore_pystate.h>
#    include <internal/pycore_tstate.h>
#endif
#undef Py_BUILD_CORE

#include <atomic>
#include <cstddef>
#include <cstring>
#ifdef __linux__
#    include <link.h>
#endif
#include <memory>
#include <mutex>
#include <vector>

#include "capture_lifetime.h"
#include "compat.h"
#include "greenlet_adapter.h"
#include "python_stack_capture.h"
#include "tracking_api.h"
#ifdef __APPLE__
#    include "macho_utils.h"
#endif

namespace memray::tracking_api::python_stack_capture {
namespace {

#if PY_VERSION_HEX >= 0x030F0000
#    if defined(__linux__) || defined(__APPLE__)
struct DirectTlsIndex
{
    size_t module;
    size_t offset;
};
static DirectTlsIndex s_direct_tls_index;
#        ifdef __linux__
extern "C" void*
__tls_get_addr(void*);
#        endif

struct TlsModuleSearch
{
    uintptr_t getter_address;
    size_t module{};
    size_t size{};
};

#        ifdef __linux__
static int
findPythonTlsModule(dl_phdr_info* info, size_t info_size, void* argument)
{
    auto& search = *static_cast<TlsModuleSearch*>(argument);
    bool contains_getter = false;
    size_t tls_size = 0;
    for (ElfW(Half) index = 0; index < info->dlpi_phnum; ++index) {
        const auto& header = info->dlpi_phdr[index];
        if (header.p_type == PT_LOAD) {
            const uintptr_t start = info->dlpi_addr + header.p_vaddr;
            contains_getter |=
                    search.getter_address >= start && search.getter_address - start < header.p_memsz;
        } else if (header.p_type == PT_TLS) {
            tls_size = header.p_memsz;
        }
    }
    if (!contains_getter) {
        return 0;
    }
    if (info_size >= offsetof(dl_phdr_info, dlpi_tls_modid) + sizeof(info->dlpi_tls_modid)) {
        search.module = info->dlpi_tls_modid;
        search.size = tls_size;
    }
    return 1;
}

#        endif

static void
findPythonTlsModule(TlsModuleSearch& search)
{
#        ifdef __APPLE__
    Dl_info owner;
    if (!dladdr(reinterpret_cast<void*>(search.getter_address), &owner)) return;
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const auto* header = _dyld_get_image_header(i);
        if (header != owner.dli_fbase) continue;
        const auto slide = _dyld_get_image_vmaddr_slide(i);
        DynamicInfoTable image(header, slide, [](const char*) { return true; });
        const auto tls = image.threadLocalStorage(slide);
        if (tls.size) {
            search.module = static_cast<size_t>(tls.key) + 1;
            search.size = tls.size;
        }
        return;
    }
#        else
    dl_iterate_phdr(findPythonTlsModule, &search);
#        endif
}

static void
initializeDirectTls()
{
    TlsModuleSearch search{reinterpret_cast<uintptr_t>(PyGILState_GetThisThreadState)};
    findPythonTlsModule(search);
    if (!search.module || search.size < sizeof(PyThreadState*)) {
        throw std::runtime_error("Cannot locate the Python TLS block");
    }

    auto* bound = PyGILState_GetThisThreadState();
    if (!bound) {
        throw std::runtime_error("Cannot initialize capture without a bound thread state");
    }
    DirectTlsIndex index{search.module, 0};
#        ifdef __APPLE__
    const auto* block = static_cast<const char*>(pthread_getspecific(index.module - 1));
    if (!block) throw std::runtime_error("Python TLS is not initialized for the current thread");
#        else
    const auto* block = static_cast<const char*>(__tls_get_addr(&index));
#        endif

    // Detach only during setup. This clears the attached-state TLS slot, so
    // the bound-state slot can be identified without a private symbol table.
    // No allocation, exception, or Python call occurs during the scan.
    auto* attached = PyEval_SaveThread();
    size_t matches = 0;
    for (size_t offset = 0; offset + sizeof(PyThreadState*) <= search.size;
         offset += alignof(PyThreadState*))
    {
        PyThreadState* candidate;
        memcpy(&candidate, block + offset, sizeof(candidate));
        if (candidate == bound) {
            index.offset = offset;
            ++matches;
        }
    }
    PyEval_RestoreThread(attached);
    if (matches != 1) {
        throw std::runtime_error("Cannot identify a unique bound-state TLS slot");
    }
    s_direct_tls_index = index;
}

static PyThreadState*
directThreadState()
{
#        ifdef __APPLE__
    const auto* block = static_cast<const char*>(pthread_getspecific(s_direct_tls_index.module - 1));
    return block ? *reinterpret_cast<PyThreadState* const*>(block + s_direct_tls_index.offset) : nullptr;
#        else
    return *static_cast<PyThreadState**>(__tls_get_addr(&s_direct_tls_index));
#        endif
}
#    else
static void
initializeDirectTls()
{
    throw std::runtime_error("Python 3.15 direct TLS capture requires Linux or macOS");
}

static PyThreadState*
directThreadState()
{
    return nullptr;
}
#    endif
#else
static pthread_key_t s_direct_tstate_key;
static void
initializeDirectTls()
{
#    if PY_VERSION_HEX >= 0x030C0000
    s_direct_tstate_key = _PyRuntime.autoTSSkey._key;
#    else
    s_direct_tstate_key = _PyRuntime.gilstate.autoTSSkey._key;
#    endif
}
static PyThreadState*
directThreadState()
{
    return static_cast<PyThreadState*>(pthread_getspecific(s_direct_tstate_key));
}
#endif

#if PY_VERSION_HEX >= 0x030B0000
using CaptureFrame = _PyInterpreterFrame;
#else
using CaptureFrame = PyFrameObject;
#endif

static CaptureFrame*
captureCurrentFrame(PyThreadState* ts)
{
#if PY_VERSION_HEX >= 0x030D0000
    return ts->current_frame;
#elif PY_VERSION_HEX >= 0x030B0000
    return ts->cframe ? ts->cframe->current_frame : nullptr;
#else
    return ts->frame;
#endif
}

static CaptureFrame*
capturePreviousFrame(CaptureFrame* frame)
{
#if PY_VERSION_HEX >= 0x030B0000
    return frame->previous;
#else
    return frame->f_back;
#endif
}

static PyCodeObject*
captureFrameCode(CaptureFrame* frame)
{
#if PY_VERSION_HEX >= 0x030F0000
    return reinterpret_cast<PyCodeObject*>(frame->f_executable.bits & ~uintptr_t(3));
#elif PY_VERSION_HEX >= 0x030E0000
    return reinterpret_cast<PyCodeObject*>(frame->f_executable.bits & ~uintptr_t(1));
#elif PY_VERSION_HEX >= 0x030D0000
    return reinterpret_cast<PyCodeObject*>(frame->f_executable);
#else
    return frame->f_code;
#endif
}

static uintptr_t
captureFrameInstruction(CaptureFrame* frame)
{
#if PY_VERSION_HEX >= 0x030D0000
    return reinterpret_cast<uintptr_t>(frame->instr_ptr);
#elif PY_VERSION_HEX >= 0x030B0000
    return reinterpret_cast<uintptr_t>(frame->prev_instr);
#else
    return static_cast<uintptr_t>(frame->f_lasti);
#endif
}

static std::atomic<uint64_t> s_code_identity_generation{};

#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
struct TlbcCache
{
    PyThreadState* thread{};
    uint64_t thread_id{};
    uint64_t generation{};
    std::unordered_map<PyCodeObject*, uintptr_t> bases;
};

static void
refreshTlbcCache(TlbcCache& cache, PyThreadState* ts)
{
    const auto generation = s_code_identity_generation.load(std::memory_order_acquire);
    if (cache.thread != ts || cache.thread_id != ts->id || cache.generation != generation) {
        cache.bases.clear();
        cache.thread = ts;
        cache.thread_id = ts->id;
        cache.generation = generation;
    }
}

static uintptr_t
captureBytecodeBase(CaptureFrame* frame, PyThreadState* ts, TlbcCache& cache, uintptr_t known_base = 0)
{
    auto* code = captureFrameCode(frame);
    if (frame->tlbc_index == 0) {
        return reinterpret_cast<uintptr_t>(code->co_code_adaptive);
    }
    // RESUME and generator.throw can allocate before they replace the frame's
    // previous thread's bytecode. Read that entry for this capture only. A
    // foreign index is not protected by the current thread's lifetime.
    const bool own_index = frame->tlbc_index == reinterpret_cast<_PyThreadStateImpl*>(ts)->tlbc_index;
    if (own_index) {
        if (known_base) return known_base;
        refreshTlbcCache(cache, ts);
        const auto found = cache.bases.find(code);
        if (found != cache.bases.end()) return found->second;
    }
    auto read_base = [&] {
        auto* table = __atomic_load_n(&code->co_tlbc, __ATOMIC_ACQUIRE);
        const int index = frame->tlbc_index;
        return table && index > 0 && index < table->size
                       ? reinterpret_cast<uintptr_t>(
                                 __atomic_load_n(&table->entries[index], __ATOMIC_ACQUIRE))
                       : uintptr_t(0);
    };
    uintptr_t base;
    if (__atomic_load_n(&ts->state, __ATOMIC_RELAXED) == _Py_THREAD_ATTACHED) {
        // Attached threads participate in CPython's reclamation protocol.
        base = read_base();
    } else {
        // MEM-domain free/realloc use the same native guard. No allocation
        // or Python call occurs while this short table read holds the guard.
        capture_lifetime::TlbcReadGuard guard;
        base = read_base();
    }
    if (base && own_index) cache.bases[code] = base;
    return base;
}

#endif

static int
captureFrameOffset(CaptureFrame* frame, [[maybe_unused]] uintptr_t bytecode_base = 0)
{
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
    const uintptr_t base = bytecode_base;
    const uintptr_t instruction = captureFrameInstruction(frame);
    const uintptr_t size = Py_SIZE(captureFrameCode(frame)) * sizeof(_Py_CODEUNIT);
    if (!base || instruction < base || instruction - base >= size
        || (instruction - base) % sizeof(_Py_CODEUNIT))
    {
        return -1;
    }
    return static_cast<int>(instruction - base);
#elif PY_VERSION_HEX >= 0x030B0000
    return static_cast<int>(
            captureFrameInstruction(frame)
            - reinterpret_cast<uintptr_t>(captureFrameCode(frame)->co_code_adaptive));
#else
    return frame->f_lasti;
#endif
}

static bool
captureFrameComplete(CaptureFrame* frame, int offset)
{
#if PY_VERSION_HEX >= 0x030C0000
    if (frame->owner >= 3) return false;
#endif
#if PY_VERSION_HEX >= 0x030B0000
    if (frame->owner == FRAME_OWNED_BY_GENERATOR) {
        return true;
    }
#    if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
    // A detached thread can lack a saved TLBC base. Keep the frame with an
    // unknown location instead of removing it from the application stack.
    if (offset < 0) {
        return true;
    }
#    endif
    return offset >= captureFrameCode(frame)->_co_firsttraceable * 2;
#else
    return true;
#endif
}

static bool
captureFrameEntry(CaptureFrame* frame)
{
#if PY_VERSION_HEX >= 0x030E0000
    return frame->previous && frame->previous->owner == FRAME_OWNED_BY_INTERPRETER;
#elif PY_VERSION_HEX >= 0x030C0000
    return frame->previous && frame->previous->owner == FRAME_OWNED_BY_CSTACK;
#elif PY_VERSION_HEX >= 0x030B0000
    return frame->is_entry;
#else
    return true;
#endif
}

static std::atomic<unsigned int> s_generation{};
static std::atomic<uint64_t> s_code_generation{};
static bool s_native;
static bool s_marker_runtime;

static bool
markerAllowed(PyThreadState* ts)
{
#ifdef MEMRAY_WITH_FRAME_MARKERS
    if (!s_marker_runtime || ts->state != 1 || !ts->holds_gil || ts->tracing || ts->what_event >= 0
        || ts->c_tracefunc || ts->c_profilefunc || !greenlet_adapter::threadKnownAbsent())
        return false;
    return true;
#else
    return false;
#endif
}

struct StackCache
{
    struct CapturedFrame
    {
        code_object_id_t code_object_id;
        PyCodeObject* code;
        uintptr_t instruction;
        int instruction_offset;
        uint8_t owner;
        bool is_entry_frame;

#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
        uintptr_t bytecode_base;
#endif

        Frame frame() const
        {
            return {code_object_id, instruction_offset, is_entry_frame};
        }

        bool sameLocation(const CapturedFrame& other) const
        {
            return code_object_id == other.code_object_id
                   && instruction_offset == other.instruction_offset
                   && is_entry_frame == other.is_entry_frame;
        }
    };

    struct MarkerAddress
    {
        uintptr_t frame;
        uintptr_t previous;
    };

    struct Change
    {
        size_t index;
        CapturedFrame current;
    };

    bool marker_reusable{};
    bool marker_no_anchor{};
    uintptr_t marker_version{};
    unsigned long marker_gil_switch{};
    unsigned int generation{};
    uint64_t code_identity_generation{};
    PyThreadState* thread{};
    uint64_t thread_id{};
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
    int tlbc_index{};
    TlbcCache tlbc;
#endif
    std::vector<MarkerAddress> marker_addresses;
    std::vector<MarkerAddress> marker_pending;
    std::vector<CapturedFrame> previous;
    std::vector<CapturedFrame> pending;
    std::vector<Change> changes;
};

MEMRAY_FAST_TLS static thread_local StackCache* t_cache;
MEMRAY_FAST_TLS static thread_local bool t_cache_destroyed;
MEMRAY_FAST_TLS static thread_local size_t t_emitted_depth;
MEMRAY_FAST_TLS static thread_local unsigned int t_emitted_generation;
static pthread_key_t s_cache_key;

static void
destroyStackCache(void* pointer)
{
    RecursionGuard guard;
    t_cache = nullptr;
    t_cache_destroyed = true;
    delete static_cast<StackCache*>(pointer);
}

static StackCache&
getStackCache()
{
    if (!t_cache) {
        RecursionGuard guard;
        auto cache = std::make_unique<StackCache>();
        cache->previous.reserve(128);
        if (s_marker_runtime) {
            cache->marker_addresses.reserve(128);
            cache->marker_pending.reserve(128);
        }
        cache->pending.reserve(128);
        cache->changes.reserve(16);
        if (pthread_setspecific(s_cache_key, cache.get()) != 0) {
            throw std::runtime_error("Failed to store the Python stack cache");
        }
        t_cache = cache.release();
    }
    return *t_cache;
}

#if PY_VERSION_HEX < 0x030C0000
static destructor s_original_code_dealloc;

static void
codeDealloc(PyObject* code)
{
    Tracker::codeObjectDestroyed(reinterpret_cast<PyCodeObject*>(code));
    s_original_code_dealloc(code);
}
#endif

}  // namespace

void
initialize()
{
    static std::once_flag once;
    std::call_once(once, [] {
        initializeDirectTls();
#ifdef MEMRAY_WITH_FRAME_MARKERS
        // Experimental exact-runtime gate. Earlier patch releases use visited in GC.
        s_marker_runtime = (Py_Version == 0x030e06f0 || Py_Version == 0x030f00c3)
                           && PySys_GetObject("gettotalrefcount") == nullptr;
#endif
        // C++ TLS destructor registration can allocate while its runtime
        // holds a once flag. Use pthread ownership to avoid recursive setup.
        if (pthread_key_create(&s_cache_key, destroyStackCache) != 0) {
            throw std::runtime_error("Failed to create the Python stack cache key");
        }
#if PY_VERSION_HEX < 0x030C0000
        // Older interpreters have no code watcher. A type destructor hook also
        // covers code objects first observed by an allocation with no GIL.
        s_original_code_dealloc = PyCode_Type.tp_dealloc;
        PyCode_Type.tp_dealloc = codeDealloc;
#endif
    });
}

bool
hasThreadState()
{
    return directThreadState() != nullptr && !t_cache_destroyed;
}

void
invalidateMarkers()
{
#ifdef MEMRAY_WITH_FRAME_MARKERS
    if (!t_cache || !t_cache->marker_reusable) return;
    // Only an active monitoring event can change a paused frame's line.
    // Use the live bound state; the cache's saved state may be gone.
#    if PY_VERSION_HEX >= 0x030F0000
    PyThreadState* ts;
    {
        // A TLS resolver can allocate when its loader state changes.
        RecursionGuard guard;
        ts = directThreadState();
    }
#    else
    auto* ts = directThreadState();
#    endif
    if (!ts || ts->state != 1 || !ts->holds_gil || ts->what_event >= 0 || ts->_status.finalizing
        || ts->_status.cleared || ts->_status.finalized)
    {
        t_cache->marker_reusable = false;
    }
#endif
}

void
beginTracking(bool native)
{
    initialize();
    s_native = native;
    s_generation.fetch_add(1, std::memory_order_relaxed);
}

void
forgetTlbcCode()
{
    s_code_identity_generation.fetch_add(1, std::memory_order_release);
}

void
invalidateCodeCache()
{
    s_code_generation.fetch_add(1, std::memory_order_release);
}

void
clear(Tracker& tracker)
{
    const auto generation = s_generation.load(std::memory_order_relaxed);
    if (t_emitted_generation == generation && t_emitted_depth) {
        tracker.popFrames(t_emitted_depth);
    }
    t_emitted_depth = 0;
    if (t_cache) {
        t_cache->previous.clear();
        t_cache->thread = nullptr;
    }
}

void
emit(Tracker& tracker)
{
    auto* ts = directThreadState();
    if (!ts || t_cache_destroyed) {
        clear(tracker);
        return;
    }

    auto& cache = getStackCache();
    const auto generation = s_generation.load(std::memory_order_relaxed);
    if (cache.generation != generation) {
        cache.previous.clear();
        cache.thread = nullptr;
        cache.generation = generation;
    }

    const auto code_generation = s_code_generation.load(std::memory_order_acquire);
    const auto identity_generation = s_code_identity_generation.load(std::memory_order_acquire);
    const bool identities_valid = cache.code_identity_generation == identity_generation;
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
    const int tlbc_index = reinterpret_cast<_PyThreadStateImpl*>(ts)->tlbc_index;
#endif
    const bool same_thread = cache.thread == ts && cache.thread_id == ts->id
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
                             && cache.tlbc_index == tlbc_index
#endif
            ;
    tracker.refreshRawCodeCache(code_generation);
    bool marker_eligible = !cache.previous.empty() && markerAllowed(ts);
    bool marker_has_anchor = false;
    uintptr_t marker_version = 0;
    unsigned long marker_gil_switch = 0;
#ifdef MEMRAY_WITH_FRAME_MARKERS
    if (marker_eligible) {
        marker_version = ts->interp->ceval.instrumentation_version;
        // A foreign callback can outlive its cleared monitoring tool. The
        // GIL counter detects that callback resuming between our captures.
        marker_gil_switch = ts->interp->ceval.gil->switch_number;
    }
#endif
    const bool marker_old_reusable = marker_eligible && cache.marker_reusable && identities_valid
                                     && same_thread && cache.marker_version == marker_version
                                     && cache.marker_gil_switch == marker_gil_switch;
    if (!marker_eligible) cache.marker_reusable = false;
#ifdef MEMRAY_WITH_FRAME_MARKERS
    if (marker_old_reusable && !cache.previous.empty()
        && cache.marker_addresses.size() == cache.previous.size())
    {
        auto* frame = captureCurrentFrame(ts);
        const auto& saved = cache.previous.front();
        const auto& address = cache.marker_addresses.front();
        if (frame && frame->owner == FRAME_OWNED_BY_THREAD && frame->owner == saved.owner
            && frame->visited == 0xa5 && reinterpret_cast<uintptr_t>(frame) == address.frame
            && reinterpret_cast<uintptr_t>(capturePreviousFrame(frame)) == address.previous
            && captureFrameCode(frame) == saved.code
            && captureFrameInstruction(frame) == saved.instruction
            && (!s_native || captureFrameEntry(frame)) == saved.is_entry_frame)
        {
            return;
        }
    }
#endif
    if ((!marker_eligible || cache.marker_no_anchor) && identities_valid && same_thread
        && !cache.previous.empty())
    {
        const auto* saved = cache.previous.data();
        const auto* end = saved + cache.previous.size();
        auto* live = captureCurrentFrame(ts);
        bool unchanged = true;
        while (live) {
#if PY_VERSION_HEX >= 0x030B0000
            const auto owner = live->owner;
#else
            const uint8_t owner = 0;
#endif
#if PY_VERSION_HEX >= 0x030C0000
            if (owner >= 3) {
                live = capturePreviousFrame(live);
                continue;
            }
#endif
            if (saved == end) {
                unchanged = false;
                break;
            }
            const uintptr_t changed = (reinterpret_cast<uintptr_t>(captureFrameCode(live))
                                       ^ reinterpret_cast<uintptr_t>(saved->code))
                                      | (captureFrameInstruction(live) ^ saved->instruction)
                                      | (static_cast<uintptr_t>(owner) ^ saved->owner)
                                      | (static_cast<uintptr_t>(!s_native || captureFrameEntry(live))
                                         ^ saved->is_entry_frame);
            if (changed
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
                || saved->instruction_offset < 0
                || !((live->tlbc_index == 0 && saved->bytecode_base == 0)
                     || (live->tlbc_index == tlbc_index && saved->bytecode_base != 0))
#endif
            )
            {
                unchanged = false;
                break;
            }
            ++saved;
            live = capturePreviousFrame(live);
        }
        if (unchanged && saved == end) {
            return;
        }
    }
    cache.changes.clear();
    cache.marker_pending.clear();
    bool marker_aligned_hit = false;
    size_t count = 0;
    for (auto* frame = captureCurrentFrame(ts); frame; frame = capturePreviousFrame(frame)) {
#if PY_VERSION_HEX >= 0x030B0000
        const uint8_t frame_owner = frame->owner;
#else
        const uint8_t frame_owner = 0;
#endif
#if PY_VERSION_HEX >= 0x030C0000
        if (frame_owner >= 3) {
            continue;
        }
#endif
        auto* code = captureFrameCode(frame);
        bool marker_was_set = false;
        bool frame_markable = false;
#ifdef MEMRAY_WITH_FRAME_MARKERS
        if (marker_eligible && frame_owner == FRAME_OWNED_BY_GENERATOR) {
            const auto instruction = reinterpret_cast<uintptr_t>(frame->instr_ptr);
            const auto base = reinterpret_cast<uintptr_t>(code->co_code_adaptive);
            const auto bytes = static_cast<uintptr_t>(Py_SIZE(code)) * sizeof(_Py_CODEUNIT);
            // Public frame constructors can leave the instruction past the code.
            if (instruction < base || instruction - base >= bytes
                || (instruction - base) % sizeof(_Py_CODEUNIT))
            {
                marker_eligible = false;
            }
        }
        if (marker_eligible && frame_owner == FRAME_OWNED_BY_GENERATOR) {
            // A pending call at RESUME can close an executing generator on
            // 3.14. Exclude resumptions and opcodes that can hide one.
            switch (frame->instr_ptr->op.code) {
                case RESUME:
                case RESUME_CHECK:
#    ifdef RESUME_CHECK_JIT
                case RESUME_CHECK_JIT:
#    endif
                case INSTRUMENTED_RESUME:
                case INSTRUMENTED_LINE:
                case INSTRUMENTED_INSTRUCTION:
                case ENTER_EXECUTOR:
                    marker_eligible = false;
                    break;
                default:
                    break;
            }
        }
        if (marker_eligible) {
            frame_markable = frame_owner == FRAME_OWNED_BY_THREAD
                             && !(code->co_flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR));
            marker_was_set = frame_markable && frame->visited == 0xa5;
        }
#endif
        auto reuse_marker_suffix = [&] {
#ifdef MEMRAY_WITH_FRAME_MARKERS
            if (!marker_eligible) return false;
            cache.marker_pending.push_back(
                    {reinterpret_cast<uintptr_t>(frame),
                     reinterpret_cast<uintptr_t>(capturePreviousFrame(frame))});
            if (!frame_markable) return false;
            // A marked ordinary activation cannot return and resume without
            // resetting its mark. Its older frames cannot resume while this
            // activation stays live. Frame edits invalidate the cache separately.
            marker_has_anchor = true;
            frame->visited = 0xa5;
            if (!marker_was_set || !marker_old_reusable) return false;
            size_t anchor = 0;
            while (anchor < cache.previous.size()
                   && cache.marker_addresses[anchor].frame != reinterpret_cast<uintptr_t>(frame))
                ++anchor;
            if (anchor == cache.previous.size()) return false;
            const auto& saved = cache.previous[anchor];
            if (saved.code != code || saved.owner != frame_owner
                || cache.marker_addresses[anchor].previous
                           != reinterpret_cast<uintptr_t>(capturePreviousFrame(frame)))
                return false;
            if (anchor + 1 == count) {
                marker_aligned_hit = true;
                count = cache.previous.size();
            } else {
                for (size_t index = anchor + 1; index < cache.previous.size(); ++index) {
                    cache.changes.push_back({count++, cache.previous[index]});
                    cache.marker_pending.push_back(cache.marker_addresses[index]);
                }
            }
            return true;
#else
            return false;
#endif
        };
        const uintptr_t instruction = captureFrameInstruction(frame);
        const bool entry = !s_native || captureFrameEntry(frame);
        const auto* previous = count < cache.previous.size() ? &cache.previous[count] : nullptr;
        const bool same_code = identities_valid && previous && code == previous->code;
        bool reusable = same_code && instruction == previous->instruction
                        && frame_owner == previous->owner && entry == previous->is_entry_frame;
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
        // A raw instruction value has the same meaning only while its code,
        // thread state and TLBC index retain their lifetimes. Unknown offsets
        // must retry the protected base read instead of becoming permanent.
        reusable = reusable && same_thread && previous->instruction_offset >= 0
                   && ((frame->tlbc_index == 0 && previous->bytecode_base == 0)
                       || (frame->tlbc_index == tlbc_index && previous->bytecode_base != 0));
#endif

        if (reusable) {
            ++count;
            if (reuse_marker_suffix()) break;
            continue;
        }
        const auto code_id = same_code ? previous->code_object_id : tracker.registerCodeObject(code);
        uintptr_t base = 0;
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
        if (same_thread && previous && code_id == previous->code_object_id) {
            base = previous->bytecode_base;
        }
        base = captureBytecodeBase(frame, ts, cache.tlbc, base);
#endif
        const int offset = captureFrameOffset(frame, base);
        if (!captureFrameComplete(frame, offset)) {
            // This frame is absent from the snapshot and cannot be an anchor.
            continue;
        }
        StackCache::CapturedFrame current{
                code_id,
                code,
                instruction,
                offset,
                frame_owner,
                entry

#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
                ,
                frame->tlbc_index != 0 && frame->tlbc_index == tlbc_index ? base : 0
#endif
        };
        cache.changes.push_back({count, current});
        ++count;
        if (reuse_marker_suffix()) break;
    }
    if (count == cache.previous.size()) {
        // A line change usually affects one leaf. Update only those copied
        // entries after the complete live chain has been inspected.
        size_t affected = 0;
        for (const auto& change : cache.changes) {
            auto& previous = cache.previous[change.index];
            if (!change.current.sameLocation(previous)) {
                affected = change.index + 1;
            }
            previous = change.current;
        }
        if (affected) {
            tracker.popFrames(affected);
            for (size_t remaining = affected; remaining; --remaining) {
                tracker.pushFrame(cache.previous[remaining - 1].frame());
            }
        }
    } else {
        const size_t retained = std::min(count, cache.previous.size());
        cache.pending.assign(cache.previous.begin(), cache.previous.begin() + retained);
        cache.pending.resize(count);
        for (const auto& change : cache.changes) {
            cache.pending[change.index] = change.current;
        }
        size_t common = 0;
        while (common < count && common < cache.previous.size()
               && cache.pending[count - common - 1].sameLocation(
                       cache.previous[cache.previous.size() - common - 1]))
        {
            ++common;
        }
        if (cache.previous.size() > common) {
            tracker.popFrames(cache.previous.size() - common);
        }
        for (size_t remaining = count - common; remaining; --remaining) {
            tracker.pushFrame(cache.pending[remaining - 1].frame());
        }
        cache.previous.swap(cache.pending);
    }
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
    cache.tlbc_index = tlbc_index;
#endif
    if (marker_eligible) {
        if (marker_aligned_hit) {
            std::copy(
                    cache.marker_pending.begin(),
                    cache.marker_pending.end(),
                    cache.marker_addresses.begin());
        } else {
            cache.marker_addresses.swap(cache.marker_pending);
        }
    } else {
        cache.marker_addresses.clear();
    }
    cache.marker_reusable = marker_eligible && marker_has_anchor;
    cache.marker_no_anchor = marker_eligible && !marker_has_anchor;
    cache.marker_version = marker_version;
    cache.marker_gil_switch = marker_gil_switch;
    cache.code_identity_generation = identity_generation;
    t_emitted_depth = count;
    t_emitted_generation = generation;
    cache.thread = ts;
    cache.thread_id = ts->id;
}

}  // namespace memray::tracking_api::python_stack_capture
