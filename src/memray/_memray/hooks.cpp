#include <cassert>
#include <cstdio>
#include <mutex>
#include <unordered_set>

#include "hooks.h"
#include "tracking_api.h"

namespace memray::hooks {

#if defined(__linux__)
int
phdr_symfind_callback(dl_phdr_info* info, [[maybe_unused]] size_t size, void* data) noexcept
{
    auto result = reinterpret_cast<symbol_query*>(data);

    // From all maps without name, we only want to visit the executable (first map)
    if (result->maps_visited++ != 0 && !info->dlpi_name[0]) {
        return 0;
    }

    if (strstr(info->dlpi_name, "linux-vdso.so.1")) {
        // This is an evil place that don't have symbols
        return 0;
    }

    for (auto phdr = info->dlpi_phdr, end = phdr + info->dlpi_phnum; phdr != end; ++phdr) {
        if (phdr->p_type != PT_DYNAMIC) {
            continue;
        }

        const auto* dyn = reinterpret_cast<const Dyn*>(phdr->p_vaddr + info->dlpi_addr);
        SymbolTable symbols(info->dlpi_addr, dyn);

        const auto offset = symbols.getSymbolAddress(result->symbol_name);
        if (offset == 0) {
            continue;
        }

        result->address = reinterpret_cast<void*>(offset);
        return 1;
    }

    return 0;
}
#endif

AllocatorKind
allocatorKind(const Allocator& allocator)
{
    switch (allocator) {
        case Allocator::CALLOC:
        case Allocator::MALLOC:
        case Allocator::MEMALIGN:
        case Allocator::POSIX_MEMALIGN:
        case Allocator::ALIGNED_ALLOC:
        case Allocator::PVALLOC:
        case Allocator::REALLOC:
        case Allocator::VALLOC:
        case Allocator::PYMALLOC_MALLOC:
        case Allocator::PYMALLOC_CALLOC:
        case Allocator::PYMALLOC_REALLOC: {
            return AllocatorKind::SIMPLE_ALLOCATOR;
        }
        case Allocator::FREE:
        case Allocator::PYMALLOC_FREE: {
            return AllocatorKind::SIMPLE_DEALLOCATOR;
        }
        case Allocator::MMAP: {
            return AllocatorKind::RANGED_ALLOCATOR;
        }
        case Allocator::MUNMAP: {
            return AllocatorKind::RANGED_DEALLOCATOR;
        }
    }
    __builtin_unreachable();
}

bool
isDeallocator(const Allocator& allocator)
{
    switch (allocatorKind(allocator)) {
        case AllocatorKind::SIMPLE_ALLOCATOR:
        case AllocatorKind::RANGED_ALLOCATOR:
            return false;
        case AllocatorKind::SIMPLE_DEALLOCATOR:
        case AllocatorKind::RANGED_DEALLOCATOR:
            return true;
    }
    __builtin_unreachable();
}

#define FOR_EACH_HOOKED_FUNCTION(f) SymbolHook<decltype(&::f)> MEMRAY_ORIG_NO_NS(f)(#f, &::f);
MEMRAY_HOOKED_FUNCTIONS
#undef FOR_EACH_HOOKED_FUNCTION

void
ensureAllHooksAreValid()
{
#define FOR_EACH_HOOKED_FUNCTION(f) MEMRAY_ORIG(f).ensureValidOriginalSymbol();
    MEMRAY_HOOKED_FUNCTIONS
#undef FOR_EACH_HOOKED_FUNCTION
}

}  // namespace memray::hooks

namespace memray::intercept {

void*
pymalloc_malloc(void* ctx, size_t size) noexcept
{
    auto* alloc = (PyMemAllocatorEx*)ctx;
    void* ptr;
    {
        tracking_api::RecursionGuard guard;
        ptr = alloc->malloc(alloc->ctx, size);
    }
    tracking_api::Tracker::trackAllocation(ptr, size, hooks::Allocator::PYMALLOC_MALLOC);
    return ptr;
}

void*
pymalloc_realloc(void* ctx, void* ptr, size_t size) noexcept
{
    auto* alloc = (PyMemAllocatorEx*)ctx;
    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = alloc->realloc(alloc->ctx, ptr, size);
    }
    if (ret) {
        if (ptr) {
            tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::PYMALLOC_FREE);
        }
        tracking_api::Tracker::trackAllocation(ret, size, hooks::Allocator::PYMALLOC_REALLOC);
    }
    return ret;
}

void*
pymalloc_calloc(void* ctx, size_t nelem, size_t size) noexcept
{
    auto* alloc = (PyMemAllocatorEx*)ctx;
    void* ptr;
    {
        tracking_api::RecursionGuard guard;
        ptr = alloc->calloc(alloc->ctx, nelem, size);
    }
    tracking_api::Tracker::trackAllocation(ptr, nelem * size, hooks::Allocator::PYMALLOC_CALLOC);
    return ptr;
}

void
pymalloc_free(void* ctx, void* ptr) noexcept
{
    auto* alloc = (PyMemAllocatorEx*)ctx;
    {
        tracking_api::RecursionGuard guard;
        alloc->free(alloc->ctx, ptr);
    }
    if (ptr) {
        tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::PYMALLOC_FREE);
    }
}

void*
malloc(size_t size) noexcept
{
    assert(MEMRAY_ORIG(malloc));

    void* ptr;
    {
        tracking_api::RecursionGuard guard;
        ptr = MEMRAY_ORIG(malloc)(size);
    }
    if (ptr) {
        tracking_api::Tracker::trackAllocation(ptr, size, hooks::Allocator::MALLOC);
    }
    return ptr;
}

void
free(void* ptr) noexcept
{
    assert(MEMRAY_ORIG(free));

    // We need to call our API before we call the real free implementation
    // to make sure that the pointer is not reused in-between.
    if (ptr != nullptr) {
        tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::FREE);
    }

    {
        tracking_api::RecursionGuard guard;
        MEMRAY_ORIG(free)(ptr);
    }
}

void*
realloc(void* ptr, size_t size) noexcept
{
    assert(MEMRAY_ORIG(realloc));

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(realloc)(ptr, size);
    }
    if (ret) {
        if (ptr != nullptr) {
            tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::FREE);
        }
        tracking_api::Tracker::trackAllocation(ret, size, hooks::Allocator::REALLOC);
    }
    return ret;
}

void*
calloc(size_t num, size_t size) noexcept
{
    assert(MEMRAY_ORIG(calloc));

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(calloc)(num, size);
    }
    if (ret) {
        tracking_api::Tracker::trackAllocation(ret, num * size, hooks::Allocator::CALLOC);
    }
    return ret;
}

void*
mmap(void* addr, size_t length, int prot, int flags, int fd, off_t offset) noexcept
{
    assert(MEMRAY_ORIG(mmap));
    void* ptr;
    {
        tracking_api::RecursionGuard guard;
        ptr = MEMRAY_ORIG(mmap)(addr, length, prot, flags, fd, offset);
    }
    if (ptr != MAP_FAILED) {
        tracking_api::Tracker::trackAllocation(ptr, length, hooks::Allocator::MMAP);
    }
    return ptr;
}

#if defined(__GLIBC__)
void*
mmap64(void* addr, size_t length, int prot, int flags, int fd, off64_t offset) noexcept
{
    assert(MEMRAY_ORIG(mmap64));
    void* ptr;
    {
        tracking_api::RecursionGuard guard;
        ptr = MEMRAY_ORIG(mmap64)(addr, length, prot, flags, fd, offset);
    }
    if (ptr != MAP_FAILED) {
        tracking_api::Tracker::trackAllocation(ptr, length, hooks::Allocator::MMAP);
    }
    return ptr;
}
#endif

int
munmap(void* addr, size_t length) noexcept
{
    assert(MEMRAY_ORIG(munmap));
    tracking_api::Tracker::trackDeallocation(addr, length, hooks::Allocator::MUNMAP);
    {
        tracking_api::RecursionGuard guard;
        return MEMRAY_ORIG(munmap)(addr, length);
    }
}

void*
valloc(size_t size) noexcept
{
    assert(MEMRAY_ORIG(valloc));

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(valloc)(size);
    }
    if (ret) {
        tracking_api::Tracker::trackAllocation(ret, size, hooks::Allocator::VALLOC);
    }
    return ret;
}

int
posix_memalign(void** memptr, size_t alignment, size_t size) noexcept
{
    assert(MEMRAY_ORIG(posix_memalign));

    int ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(posix_memalign)(memptr, alignment, size);
    }
    if (!ret) {
        tracking_api::Tracker::trackAllocation(*memptr, size, hooks::Allocator::POSIX_MEMALIGN);
    }
    return ret;
}

// We need to override dlopen/dlclose to account for new shared libraries being
// loaded in the process memory space. This is needed so we can correctly track
// allocations in those libraries by overriding their PLT entries and also so we
// can properly map the addresses of the symbols in those libraries when we
// resolve later native traces. Unfortunately, we can't just override dlopen
// directly because of the following edge case: when a shared library dlopen's
// another by name (e.g. dlopen("libfoo.so")), the dlopen call will honor the
// RPATH/RUNPATH of the calling library if it's set. Some libraries set an
// RPATH/RUNPATH based on $ORIGIN (the path of the calling library) to load
// dependencies from a relative directory based on the location of the calling
// library. This means that if we override dlopen, we'll end up loading the
// library from the wrong path or more likely, not loading it at all because the
// dynamic loader will think the memray extenion it's the calling library and
// the RPATH of the real calling library will not be honoured.
//
// To work around this, we override dlsym instead and override the symbols in
// the loaded libraries only the first time we have seen a handle passed to
// dlsym. This works because for a symbol from a given dlopen-ed library to
// appear in a call stack, *something* from that library has to be dlsym-ed
// first. The only exception to this are static initializers, but we cannot
// track those anyway by overriding dlopen as they run within the dlopen call
// itself.
// There's another set of cases we would miss: if library A has a static initializer
// that passes a pointer to one of its functions to library B, and library B stores
// that function pointer, then we could see calls into library A via the function pointer
// held by library B, even though dlsym was never called on library A. This should be
// very rare and will be corrected the next time library B calls dlsym so this should
// not be a problem in practice.

class DlsymCache
{
  public:
    auto insert(const void* handle)
    {
        std::unique_lock lock(mutex_);
        return d_handles.insert(handle);
    }

    void erase(const void* handle)
    {
        std::unique_lock lock(mutex_);
        d_handles.erase(handle);
    }

  private:
    mutable std::mutex mutex_;
    std::unordered_set<const void*> d_handles;
};

static DlsymCache dlsym_cache;

void*
dlsym(void* handle, const char* symbol) noexcept
{
    assert(MEMRAY_ORIG(dlsym));
    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(dlsym)(handle, symbol);
    }
    if (ret) {
        auto [_, inserted] = dlsym_cache.insert(handle);
        if (inserted) {
            tracking_api::Tracker::invalidate_module_cache();
            if (symbol
                && (0 == strcmp(symbol, "PyInit_greenlet") || 0 == strcmp(symbol, "PyInit__greenlet")))
            {
                tracking_api::Tracker::beginTrackingGreenlets();
            }
        }
    }
    return ret;
}

int
dlclose(void* handle) noexcept
{
    assert(MEMRAY_ORIG(dlclose));

    int ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(dlclose)(handle);
    }
    dlsym_cache.erase(handle);
    tracking_api::NativeTrace::flushCache();
    if (!ret) tracking_api::Tracker::invalidate_module_cache();
    return ret;
}

void*
aligned_alloc(size_t alignment, size_t size) noexcept
{
    assert(MEMRAY_ORIG(aligned_alloc));

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(aligned_alloc)(alignment, size);
    }
    if (ret) {
        tracking_api::Tracker::trackAllocation(ret, size, hooks::Allocator::ALIGNED_ALLOC);
    }
    return ret;
}

#if defined(__linux__)

void*
memalign(size_t alignment, size_t size) noexcept
{
    assert(MEMRAY_ORIG(memalign));

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(memalign)(alignment, size);
    }
    if (ret) {
        tracking_api::Tracker::trackAllocation(ret, size, hooks::Allocator::MEMALIGN);
    }
    return ret;
}

#    if defined(__GLIBC__)
void*
pvalloc(size_t size) noexcept
{
    assert(MEMRAY_ORIG(pvalloc));

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = MEMRAY_ORIG(pvalloc)(size);
    }
    if (ret) {
        tracking_api::Tracker::trackAllocation(ret, size, hooks::Allocator::PVALLOC);
    }
    return ret;
}
#    endif

int
prctl(int option, ...) noexcept
{
    unsigned long args[4];
    va_list arguments;
    va_start(arguments, option);
    for (int i = 0; i < 4; i++) {
        args[i] = va_arg(arguments, unsigned long);
    }
    va_end(arguments);

    if (option == PR_SET_NAME) {
        char* name = reinterpret_cast<char*>(args[0]);
        tracking_api::Tracker::registerThreadName(name);
    }

    unsigned long ret = MEMRAY_ORIG(prctl)(option, args[0], args[1], args[2], args[3]);

    return ret;
}
#endif

PyGILState_STATE
PyGILState_Ensure() noexcept
{
    PyGILState_STATE ret = MEMRAY_ORIG(PyGILState_Ensure)();
    tracking_api::install_trace_function();
    return ret;
}

}  // namespace memray::intercept
