#include <Python.h>

#ifdef _PyGC_FINALIZED
#    undef _PyGC_FINALIZED
#endif
#define Py_BUILD_CORE
#if PY_VERSION_HEX < 0x030D0000
#    undef HAVE_STD_ATOMIC
#endif
#if PY_VERSION_HEX >= 0x030C0000
#    include <internal/pycore_runtime.h>
#else
#    include <internal/pycore_pymem.h>
#endif
#undef Py_BUILD_CORE

#if PY_VERSION_HEX < 0x030C0000
#    include <cstdint>
#    include <dlfcn.h>
#endif

#include <array>
#include <atomic>
#include <mutex>
#include <stdexcept>

#include "capture_lifetime.h"
#include "compat.h"
#include "greenlet_adapter.h"
#include "python_stack_capture.h"
#include "tracking_api.h"

namespace memray::tracking_api::capture_lifetime {
namespace {

struct SavedAllocators
{
    PyMemAllocatorEx* mem;
    PyMemAllocatorEx* obj;
    bool tracing;
};

bool
validTable(const PyMemAllocatorEx* allocator)
{
    return allocator && allocator->malloc && allocator->calloc && allocator->realloc && allocator->free;
}

#if PY_VERSION_HEX < 0x030C0000
PyMemAllocatorEx* saved_mem;
PyMemAllocatorEx* saved_obj;

bool
sameCallbacks(const PyMemAllocatorEx& left, const PyMemAllocatorEx& right)
{
    return left.malloc == right.malloc && left.calloc == right.calloc && left.realloc == right.realloc
           && left.free == right.free;
}

bool
sameTracemallocImage(void* callback)
{
    static void* owner = dlsym(RTLD_DEFAULT, "PyTraceMalloc_Track");
    Dl_info callback_info{};
    Dl_info owner_info{};
    return dladdr(callback, &callback_info) && owner && dladdr(owner, &owner_info)
           && callback_info.dli_fbase == owner_info.dli_fbase;
}

void
locateSavedAllocators()
{
    PyMemAllocatorEx raw;
    PyMemAllocatorEx mem;
    PyMemAllocatorEx obj;
    PyMem_GetAllocator(PYMEM_DOMAIN_RAW, &raw);
    PyMem_GetAllocator(PYMEM_DOMAIN_MEM, &mem);
    PyMem_GetAllocator(PYMEM_DOMAIN_OBJ, &obj);

    // CPython 3.9-3.11 keeps these tables in a static {mem, raw, obj} array.
    // Its live callbacks expose the three table addresses through their ctx.
    // Validate the complete layout and callback ownership before retaining it.
    const auto mem_address = reinterpret_cast<uintptr_t>(mem.ctx);
    const auto raw_address = reinterpret_cast<uintptr_t>(raw.ctx);
    const auto obj_address = reinterpret_cast<uintptr_t>(obj.ctx);
    if (!mem_address || raw_address <= mem_address || obj_address <= mem_address
        || raw_address - mem_address != sizeof(PyMemAllocatorEx)
        || obj_address - mem_address != 2 * sizeof(PyMemAllocatorEx) || !sameCallbacks(mem, obj)
        || raw.free != mem.free || !sameTracemallocImage(reinterpret_cast<void*>(mem.malloc))
        || !sameTracemallocImage(reinterpret_cast<void*>(mem.calloc))
        || !sameTracemallocImage(reinterpret_cast<void*>(mem.realloc))
        || !sameTracemallocImage(reinterpret_cast<void*>(mem.free))
        || !sameTracemallocImage(reinterpret_cast<void*>(raw.malloc))
        || !sameTracemallocImage(reinterpret_cast<void*>(raw.calloc))
        || !sameTracemallocImage(reinterpret_cast<void*>(raw.realloc)))
    {
        return;
    }
    PyMemAllocatorEx saved[3];
    if (compat::copyReadableMemory(saved, mem.ctx, sizeof(saved)) != sizeof(saved)
        || !validTable(&saved[0]) || !validTable(&saved[1]) || !validTable(&saved[2]))
    {
        return;
    }
    saved_mem = static_cast<PyMemAllocatorEx*>(mem.ctx);
    saved_obj = static_cast<PyMemAllocatorEx*>(obj.ctx);
}

#endif

SavedAllocators
savedAllocators()
{
#if PY_VERSION_HEX >= 0x030C0000
    auto& state = _PyRuntime.tracemalloc;
    return {&state.allocators.mem,
            &state.allocators.obj,
            __atomic_load_n(&state.config.tracing, __ATOMIC_ACQUIRE) != 0};
#else
    const bool tracing = _Py_tracemalloc_config.tracing != 0;
    if (tracing && !saved_mem) locateSavedAllocators();
    return {saved_mem, saved_obj, tracing};
#endif
}

// Other allocators can retain these callbacks after shutdown. Published
// contexts are process-lived, and their original callback tables never change.
struct AllocatorContext
{
    const PyMemAllocatorEx original;
    const PyMemAllocatorDomain domain;
    std::atomic<bool> active{};
    AllocatorContext* next;
};
AllocatorContext* s_contexts{};
std::array<AllocatorContext*, 4> s_active_contexts{};
// A child process cannot use or destroy a mutex held by a vanished thread.
// Its at-fork callback abandons that mutex and installs a new one.
std::mutex* s_tlbc_mutex = new std::mutex;
MEMRAY_FAST_TLS thread_local unsigned int t_lock_depth;

void
waitForReaders([[maybe_unused]] PyMemAllocatorDomain domain)
{
#if defined(Py_GIL_DISABLED) && PY_VERSION_HEX >= 0x030E0000
    if (domain == PYMEM_DOMAIN_MEM) {
        // CPython publishes a replacement co_tlbc before retiring the old
        // table. Drain existing readers. Later readers acquire this mutex
        // after that publication and cannot load the retired table.
        TlbcReadGuard guard;
    }
#endif
}

void*
allocate(void* context, size_t size)
{
    auto& original = static_cast<AllocatorContext*>(context)->original;
    return original.malloc(original.ctx, size);
}

void*
allocateZeroed(void* context, size_t count, size_t size)
{
    auto& original = static_cast<AllocatorContext*>(context)->original;
    return original.calloc(original.ctx, count, size);
}

void*
resize(void* context, void* pointer, size_t size)
{
    auto& allocator = *static_cast<AllocatorContext*>(context);
    auto& original = allocator.original;
    if (!allocator.active.load(std::memory_order_acquire)) {
        return original.realloc(original.ctx, pointer, size);
    }
    // Greenlet implementation objects do not resize. Invalidate before a
    // realloc can release an address, even if another allocator uses it here.
    greenlet_adapter::forgetAllocation(pointer);
    waitForReaders(allocator.domain);
    return original.realloc(original.ctx, pointer, size);
}

void
release(void* context, void* pointer)
{
    auto& allocator = *static_cast<AllocatorContext*>(context);
    auto& original = allocator.original;
    if (!allocator.active.load(std::memory_order_acquire)) {
        original.free(original.ctx, pointer);
        return;
    }
#ifdef MEMRAY_WITH_FRAME_MARKERS
    // Every successful f_lineno edit frees MEM scratch before it changes the
    // instruction pointer. The active-event guard prevents rearming inside
    // the setter; a GIL switch invalidates other threads' saved ancestry.
    if (allocator.domain == PYMEM_DOMAIN_MEM) python_stack_capture::invalidateMarkers();
#endif
    greenlet_adapter::forgetAllocation(pointer);
    // No lifetime lock remains held during the original allocator. Its
    // libc hooks can therefore retain their normal allocation records.
    waitForReaders(allocator.domain);
    original.free(original.ctx, pointer);
}

AllocatorContext*
contextFor(PyMemAllocatorDomain domain, const PyMemAllocatorEx& original)
{
    // Setup runs with Python stopped. Allocation callbacks never read the
    // list. Reusing an exact table avoids one retained context per session.
    for (auto* context = s_contexts; context; context = context->next) {
        if (context->domain == domain && sameAllocator(context->original, original)) {
            return context;
        }
    }
    auto* context = new AllocatorContext{original, domain, {}, s_contexts};
    s_contexts = context;
    return context;
}

PyMemAllocatorEx
wrapperFor(AllocatorContext& context)
{
    return {&context, allocate, allocateZeroed, resize, release};
}

void
restore(PyMemAllocatorDomain domain, AllocatorContext& context)
{
    PyMemAllocatorEx current;
    PyMem_GetAllocator(domain, &current);
    if (sameAllocator(current, wrapperFor(context))) {
        auto original = context.original;
        PyMem_SetAllocator(domain, &original);
    }
}

bool
unwrapLifetimeAllocator(PyMemAllocatorEx& allocator)
{
    for (auto* context = s_contexts; context; context = context->next) {
        if (!context->active.load(std::memory_order_acquire)
            && sameAllocator(allocator, wrapperFor(*context)))
        {
            allocator = context->original;
            return true;
        }
    }
    return false;
}

void
unwrapSavedAllocator(PyMemAllocatorEx& allocator)
{
    while (unwrapLifetimeAllocator(allocator) || unwrapPymallocAllocator(&allocator)) {
    }
}

void
unwrapCurrentAllocator(PyMemAllocatorDomain domain)
{
    PyMemAllocatorEx current;
    PyMem_GetAllocator(domain, &current);
    auto original = current;
    unwrapSavedAllocator(original);
    if (!sameAllocator(current, original)) PyMem_SetAllocator(domain, &original);
}

}  // namespace

void
activate()
{
    PyMemAllocatorEx mem_original;
    PyMemAllocatorEx obj_original;
    PyMem_GetAllocator(PYMEM_DOMAIN_MEM, &mem_original);
    PyMem_GetAllocator(PYMEM_DOMAIN_OBJ, &obj_original);
    // tracemalloc.stop restores these tables and can remove an outer wrapper.
    // Protect the saved underlying allocators as well. Their contexts must
    // never contain tracemalloc's live table, which points back at these slots.
    const auto saved = savedAllocators();
    AllocatorContext* inner_mem = nullptr;
    AllocatorContext* inner_obj = nullptr;
    if (saved.tracing && (!validTable(saved.mem) || !validTable(saved.obj))) {
        throw std::runtime_error("Cannot locate tracemalloc's saved memory allocators");
    }
    // tracemalloc installs callbacks before it publishes config.tracing.
    // An initialized saved table also needs protection in that interval.
    if (validTable(saved.mem)) {
        auto saved_mem = *saved.mem;
        unwrapSavedAllocator(saved_mem);
        inner_mem = contextFor(PYMEM_DOMAIN_MEM, saved_mem);
    }
    if (validTable(saved.obj)) {
        auto saved_obj = *saved.obj;
        unwrapSavedAllocator(saved_obj);
        inner_obj = contextFor(PYMEM_DOMAIN_OBJ, saved_obj);
    }
    // Prepare both contexts before changing either allocator slot. If the
    // second allocation fails, the original slots remain intact.
    auto* mem = contextFor(PYMEM_DOMAIN_MEM, mem_original);
    auto* obj = contextFor(PYMEM_DOMAIN_OBJ, obj_original);
    auto mem_wrapper = wrapperFor(*mem);
    auto obj_wrapper = wrapperFor(*obj);
    s_active_contexts = {mem, obj, inner_mem, inner_obj};
    if (inner_mem) {
        inner_mem->active.store(true, std::memory_order_release);
        *saved.mem = wrapperFor(*inner_mem);
    }
    if (inner_obj) {
        inner_obj->active.store(true, std::memory_order_release);
        *saved.obj = wrapperFor(*inner_obj);
    }
    mem->active.store(true, std::memory_order_release);
    obj->active.store(true, std::memory_order_release);
    PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &mem_wrapper);
    PyMem_SetAllocator(PYMEM_DOMAIN_OBJ, &obj_wrapper);
}

void
deactivate()
{
    for (auto* context : s_active_contexts) {
        if (context) context->active.store(false, std::memory_order_release);
    }
    for (auto* context : s_active_contexts) {
        if (context) restore(context->domain, *context);
    }
    unwrapCurrentAllocator(PYMEM_DOMAIN_MEM);
    unwrapCurrentAllocator(PYMEM_DOMAIN_OBJ);
    // tracemalloc can also start during Tracker. Its MEM/OBJ callers are
    // attached, so setup can remove inactive wrappers while Python is stopped.
    // RAW callers can remain detached. Their immutable inactive wrappers stay.
    const auto saved = savedAllocators();
    if (saved.mem) unwrapSavedAllocator(*saved.mem);
    if (saved.obj) unwrapSavedAllocator(*saved.obj);
    s_active_contexts.fill(nullptr);
}

TlbcReadGuard::TlbcReadGuard()
{
    if (t_lock_depth++ == 0) s_tlbc_mutex->lock();
}

TlbcReadGuard::~TlbcReadGuard()
{
    if (--t_lock_depth == 0) s_tlbc_mutex->unlock();
}

void
childFork()
{
    auto* mutex = new std::mutex;
    // A guard on this thread's surviving stack must still unlock once.
    // Locks held by all other threads belong to the abandoned mutex.
    if (t_lock_depth) mutex->lock();
    s_tlbc_mutex = mutex;
}

}  // namespace memray::tracking_api::capture_lifetime
