#include <cassert>
#include <cstdio>

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

#define FOR_EACH_HOOKED_FUNCTION(f) SymbolHook<decltype(&::f)> f(#f, &::f);
MEMRAY_HOOKED_FUNCTIONS
#undef FOR_EACH_HOOKED_FUNCTION

void
ensureAllHooksAreValid()
{
#define FOR_EACH_HOOKED_FUNCTION(f) f.ensureValidOriginalSymbol();
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
    assert(hooks::malloc);

    void* ptr = hooks::malloc(size);
    tracking_api::Tracker::trackAllocation(ptr, size, hooks::Allocator::MALLOC);
    return ptr;
}

void
free(void* ptr) noexcept
{
    assert(hooks::free);

    // We need to call our API before we call the real free implementation
    // to make sure that the pointer is not reused in-between.
    if (ptr != nullptr) {
        tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::FREE);
    }

    hooks::free(ptr);
}

void*
realloc(void* ptr, size_t size) noexcept
{
    assert(hooks::realloc);

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::realloc(ptr, size);
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
    assert(hooks::calloc);

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::calloc(num, size);
    }
    if (ret) {
        tracking_api::Tracker::trackAllocation(ret, num * size, hooks::Allocator::CALLOC);
    }
    return ret;
}

void*
mmap(void* addr, size_t length, int prot, int flags, int fd, off_t offset) noexcept
{
    assert(hooks::mmap);
    void* ptr = hooks::mmap(addr, length, prot, flags, fd, offset);
    tracking_api::Tracker::trackAllocation(ptr, length, hooks::Allocator::MMAP);
    return ptr;
}

#if defined(__GLIBC__)
void*
mmap64(void* addr, size_t length, int prot, int flags, int fd, off64_t offset) noexcept
{
    assert(hooks::mmap64);
    void* ptr = hooks::mmap64(addr, length, prot, flags, fd, offset);
    tracking_api::Tracker::trackAllocation(ptr, length, hooks::Allocator::MMAP);
    return ptr;
}
#endif

int
munmap(void* addr, size_t length) noexcept
{
    assert(hooks::munmap);
    tracking_api::Tracker::trackDeallocation(addr, length, hooks::Allocator::MUNMAP);
    return hooks::munmap(addr, length);
}

void*
valloc(size_t size) noexcept
{
    assert(hooks::valloc);

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::valloc(size);
    }
    if (ret) {
        tracking_api::Tracker::trackAllocation(ret, size, hooks::Allocator::VALLOC);
    }
    return ret;
}

int
posix_memalign(void** memptr, size_t alignment, size_t size) noexcept
{
    assert(hooks::posix_memalign);

    int ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::posix_memalign(memptr, alignment, size);
    }
    if (!ret) {
        tracking_api::Tracker::trackAllocation(*memptr, size, hooks::Allocator::POSIX_MEMALIGN);
    }
    return ret;
}

void*
dlopen(const char* filename, int flag) noexcept
{
    assert(hooks::dlopen);
    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::dlopen(filename, flag);
    }
    if (ret) {
        tracking_api::Tracker::invalidate_module_cache();
        if (filename && nullptr != strstr(filename, "/_greenlet.")) {
            tracking_api::Tracker::beginTrackingGreenlets();
        }
    }
    return ret;
}

int
dlclose(void* handle) noexcept
{
    assert(hooks::dlclose);

    int ret = hooks::dlclose(handle);
    tracking_api::NativeTrace::flushCache();
    if (!ret) tracking_api::Tracker::invalidate_module_cache();
    return ret;
}

void*
aligned_alloc(size_t alignment, size_t size) noexcept
{
    assert(hooks::aligned_alloc);

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::aligned_alloc(alignment, size);
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
    assert(hooks::memalign);

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::memalign(alignment, size);
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
    assert(hooks::pvalloc);

    void* ret = hooks::pvalloc(size);
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

    unsigned long ret = hooks::prctl(option, args[0], args[1], args[2], args[3]);

    return ret;
}
#endif

PyGILState_STATE
PyGILState_Ensure() noexcept
{
    PyGILState_STATE ret = hooks::PyGILState_Ensure();
    tracking_api::install_trace_function();
    return ret;
}

}  // namespace memray::intercept
