#include "hooks.h"
#include "tracking_api.h"
#include <cassert>

namespace pensieve::hooks {

SymbolHook<decltype(&::malloc)> malloc("malloc", &::malloc);
SymbolHook<decltype(&::free)> free("free", &::free);
SymbolHook<decltype(&::calloc)> calloc("calloc", &::calloc);
SymbolHook<decltype(&::realloc)> realloc("realloc", &::realloc);
SymbolHook<decltype(&::posix_memalign)> posix_memalign("posix_memalign", &::posix_memalign);
SymbolHook<decltype(&::valloc)> valloc("valloc", &::valloc);
SymbolHook<decltype(&::dlopen)> dlopen("dlopen", &::dlopen);
SymbolHook<decltype(&::dlclose)> dlclose("dlclose", &::dlclose);
SymbolHook<decltype(&::mmap)> mmap("mmap", &::mmap);
SymbolHook<decltype(&::mmap64)> mmap64("mmap64", &::mmap64);
SymbolHook<decltype(&::munmap)> munmap("munmap", &::munmap);

}  // namespace pensieve::hooks

namespace pensieve::intercept {

void*
mmap(void* addr, size_t length, int prot, int flags, int fd, off_t offset) noexcept
{
    assert(hooks::mmap);
    void* ptr = hooks::mmap(addr, length, prot, flags, fd, offset);
    tracking_api::track_allocation(ptr, length, "mmap");
    return ptr;
}

void*
mmap64(void* addr, size_t length, int prot, int flags, int fd, off_t offset) noexcept
{
    assert(hooks::mmap64);
    void* ptr = hooks::mmap64(addr, length, prot, flags, fd, offset);
    tracking_api::track_allocation(ptr, length, "mmap64");
    return ptr;
}

int
munmap(void* addr, size_t length) noexcept
{
    assert(hooks::munmap);
    tracking_api::track_deallocation(addr, "munmap");
    return hooks::munmap(addr, length);
}

void*
malloc(size_t size) noexcept
{
    assert(hooks::track_allocation);

    void* ptr = hooks::malloc(size);
    tracking_api::track_allocation(ptr, size, "malloc");
    return ptr;
}

void
free(void* ptr) noexcept
{
    assert(hooks::free);

    // We need to call our API before we call the real free implementation
    // to make sure that the pointer is not reused in-between.
    tracking_api::track_deallocation(ptr, "free");

    hooks::free(ptr);
}

void*
realloc(void* ptr, size_t size) noexcept
{
    assert(hooks::realloc);

    void* ret = hooks::realloc(ptr, size);
    if (ret) {
        tracking_api::track_deallocation(ptr, "realloc");
        tracking_api::track_allocation(ret, size, "realloc");
    }
    return ret;
}

void*
calloc(size_t num, size_t size) noexcept
{
    assert(hooks::calloc);

    void* ret = hooks::calloc(num, size);
    if (ret) {
        tracking_api::track_allocation(ret, num * size, "calloc");
    }
    return ret;
}

int
posix_memalign(void** memptr, size_t alignment, size_t size) noexcept
{
    assert(hooks::posix_memalign);

    int ret = hooks::posix_memalign(memptr, alignment, size);
    if (!ret) {
        tracking_api::track_allocation(*memptr, size, "posix_memalign");
    }
    return ret;
}

void*
valloc(size_t size) noexcept
{
    assert(hooks::valloc);

    void* ret = hooks::valloc(size);
    if (ret) {
        tracking_api::track_allocation(ret, size, "valloc");
    }
    return ret;
}

void*
dlopen(const char* filename, int flag) noexcept
{
    assert(hooks::dlopen);

    void* ret = hooks::dlopen(filename, flag);
    if (ret) tracking_api::invalidate_module_cache();
    return ret;
}

int
dlclose(void* handle) noexcept
{
    assert(hooks::dlclose);

    int ret = hooks::dlclose(handle);
    if (!ret) tracking_api::invalidate_module_cache();
    return ret;
}

}  // namespace pensieve::intercept
