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

MEMRAY_FAST_TLS static thread_local TlbcCache* t_tlbc;

static TlbcCache*
getTlbcCache(PyThreadState* ts)
{
    if (!t_tlbc) return nullptr;
    auto& cache = *t_tlbc;
    const auto generation = s_code_identity_generation.load(std::memory_order_acquire);
    if (cache.thread != ts || cache.thread_id != ts->id || cache.generation != generation) {
        cache.bases.clear();
        cache.thread = ts;
        cache.thread_id = ts->id;
        cache.generation = generation;
    }
    return &cache;
}

static uintptr_t
captureBytecodeBase(CaptureFrame* frame, PyThreadState* ts, uintptr_t known_base = 0)
{
    auto* code = captureFrameCode(frame);
    if (frame->tlbc_index == 0) {
        return reinterpret_cast<uintptr_t>(code->co_code_adaptive);
    }
    // RESUME and generator.throw can allocate before they replace the frame's
    // previous thread's bytecode. Read that entry for this capture only. A
    // foreign index is not protected by the current thread's lifetime.
    const bool own_index = frame->tlbc_index == reinterpret_cast<_PyThreadStateImpl*>(ts)->tlbc_index;
    TlbcCache* cache = nullptr;
    if (own_index) {
        if (known_base) return known_base;
        cache = getTlbcCache(ts);
        if (!cache) return 0;
        const auto found = cache->bases.find(code);
        if (found != cache->bases.end()) return found->second;
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
    if (base && cache) cache->bases[code] = base;
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

}  // namespace
}  // namespace memray::tracking_api::python_stack_capture
