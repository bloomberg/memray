#ifndef _PENSIEVE_HOOKS_H
#define _PENSIEVE_HOOKS_H

#include <cstdio>
#include <cstdlib>
#include <malloc.h>
#include <stdexcept>
#include <string>

#include <dlfcn.h>  // dlsym
#include <sys/mman.h>

#include <Python.h>

namespace pensieve::hooks {
_Pragma("GCC diagnostic ignored \"-Wignored-attributes\"") template<typename Signature>
struct SymbolHook
{
    const char* symbol;
    using signature_t = Signature;
    signature_t original = nullptr;

    explicit SymbolHook(const char* symbol, signature_t original)
    : symbol(symbol)
    , original(original){};

    template<typename... Args>
    auto operator()(Args... args) const noexcept -> decltype(original(args...))
    {
        return this->original(args...);
    }

    explicit operator bool() const noexcept
    {
        return this->original;
    }
};

extern SymbolHook<decltype(&::malloc)> malloc;
extern SymbolHook<decltype(&::free)> free;
extern SymbolHook<decltype(&::calloc)> calloc;
extern SymbolHook<decltype(&::realloc)> realloc;
extern SymbolHook<decltype(&::posix_memalign)> posix_memalign;
extern SymbolHook<decltype(&::memalign)> memalign;
extern SymbolHook<decltype(&::valloc)> valloc;
extern SymbolHook<decltype(&::pvalloc)> pvalloc;
extern SymbolHook<decltype(&::dlopen)> dlopen;
extern SymbolHook<decltype(&::dlclose)> dlclose;
extern SymbolHook<decltype(&::mmap)> mmap;
extern SymbolHook<decltype(&::mmap64)> mmap64;
extern SymbolHook<decltype(&::munmap)> munmap;
extern SymbolHook<decltype(&::PyGILState_Ensure)> PyGILState_Ensure;

}  // namespace pensieve::hooks

namespace pensieve::intercept {
void*
malloc(size_t size) noexcept;

void
free(void* ptr) noexcept;

void*
realloc(void* ptr, size_t size) noexcept;

void*
calloc(size_t num, size_t size) noexcept;

int
posix_memalign(void** memptr, size_t alignment, size_t size) noexcept;

void*
memalign(size_t alignment, size_t size) noexcept;

void*
valloc(size_t size) noexcept;

void*
pvalloc(size_t size) noexcept;

void*
dlopen(const char* filename, int flag) noexcept;

int
dlclose(void* handle) noexcept;

void*
mmap(void* addr, size_t length, int prot, int flags, int fd, off_t offset) noexcept;

void*
mmap64(void* addr, size_t length, int prot, int flags, int fd, off_t offset) noexcept;

int
munmap(void* addr, size_t length) noexcept;

PyGILState_STATE
PyGILState_Ensure() noexcept;

}  // namespace pensieve::intercept

#endif  //_PENSIEVE_HOOKS_H
