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

void*
dlopen(const char* filename, int flag) noexcept
{
    assert(MEMRAY_ORIG(dlopen));
    void* ret = nullptr;
    {
        tracking_api::RecursionGuard guard;
#if defined(__GLIBC__)
        // In GLIBC, dlopen() will respect the RPATH/RUNPATH of the caller when searching for the
        // library, which won't work if we intercept dlopen() as we will be the caller. This means that
        // callers that rely on RUNPATH to find their dependencies will fail to load. To work around
        // this, we need to manually find our caller and walk the linker search path to know what we need
        // to dlopen().
        if (filename != nullptr && filename[0] != '\0' && std::strchr(filename, '/') == nullptr) {
            void* const callerAddr = __builtin_extract_return_addr(__builtin_return_address(0));

            Dl_info info;
            if (dladdr(callerAddr, &info)) {
                const char* dlname = info.dli_fname;
                {
                    // Check if we are being called from the main executable
                    Dl_info main_info;
                    void* main_sym = NULL;
                    void* self_handle = MEMRAY_ORIG(dlopen)(nullptr, RTLD_LAZY | RTLD_NOLOAD);
                    if (self_handle) {
                        main_sym = dlsym(self_handle, "main");
                        MEMRAY_ORIG(dlclose)(self_handle);
                    }
                    if (main_sym && dladdr(main_sym, &main_info)
                        && strcmp(main_info.dli_fname, info.dli_fname) == 0)
                    {
                        dlname = nullptr;
                    }
                }

                void* caller = MEMRAY_ORIG(dlopen)(dlname, RTLD_LAZY | RTLD_NOLOAD);
                if (caller != nullptr) {
                    Dl_serinfo size;
                    if (dlinfo(caller, RTLD_DI_SERINFOSIZE, &size) == 0) {
                        std::vector<char> paths_buf;
                        paths_buf.resize(size.dls_size);
                        auto paths = reinterpret_cast<Dl_serinfo*>(paths_buf.data());
                        *paths = size;
                        if (dlinfo(caller, RTLD_DI_SERINFO, paths) == 0) {
                            for (unsigned int i = 0; i != paths->dls_cnt; ++i) {
                                const char* name = paths->dls_serpath[i].dls_name;
                                if (name == nullptr || name[0] == '\0') {
                                    continue;
                                }
                                std::string dir = name;
                                if (dir.back() != '/') {
                                    dir += '/';
                                }

                                dir += filename;
                                ret = MEMRAY_ORIG(dlopen)(dir.c_str(), flag);
                                if (ret) {
                                    break;
                                }
                            }
                        }
                    }
                    MEMRAY_ORIG(dlclose)(caller);
                }
            }
        }
#endif
        // Fallback if we found nothing
        if (ret == nullptr) {
            ret = MEMRAY_ORIG(dlopen)(filename, flag);
        }
    }
    if (ret) {
        tracking_api::Tracker::invalidate_module_cache();
        if (filename
            && (nullptr != strstr(filename, "/_greenlet.") || nullptr != strstr(filename, "/greenlet.")))
        {
            tracking_api::Tracker::beginTrackingGreenlets();
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
