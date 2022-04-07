#ifndef _PENSIEVE_HOOKS_H
#define _PENSIEVE_HOOKS_H

#include <cstdlib>
#include <iostream>
#include <malloc.h>

#include "elf_utils.h"
#include <dlfcn.h>
#include <sys/mman.h>
#include <sys/prctl.h>

#include <Python.h>

#include "logging.h"

#define PENSIEVE_HOOKED_FUNCTIONS                                                                       \
    FOR_EACH_HOOKED_FUNCTION(malloc)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(free)                                                                      \
    FOR_EACH_HOOKED_FUNCTION(calloc)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(realloc)                                                                   \
    FOR_EACH_HOOKED_FUNCTION(posix_memalign)                                                            \
    FOR_EACH_HOOKED_FUNCTION(memalign)                                                                  \
    FOR_EACH_HOOKED_FUNCTION(valloc)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(pvalloc)                                                                   \
    FOR_EACH_HOOKED_FUNCTION(dlopen)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(dlclose)                                                                   \
    FOR_EACH_HOOKED_FUNCTION(mmap)                                                                      \
    FOR_EACH_HOOKED_FUNCTION(mmap64)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(munmap)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(prctl)                                                                     \
    FOR_EACH_HOOKED_FUNCTION(PyGILState_Ensure)

namespace memray::hooks {

struct symbol_query
{
    size_t maps_visited;
    const char* symbol_name;
    void* address;
};

int
phdr_symfind_callback(dl_phdr_info* info, [[maybe_unused]] size_t size, void* data) noexcept;

_Pragma("GCC diagnostic ignored \"-Wignored-attributes\"") template<typename Signature>
struct SymbolHook
{
    using signature_t = Signature;
    const char* d_symbol;
    signature_t d_original = nullptr;

    explicit SymbolHook(const char* symbol, signature_t original)
    : d_symbol(symbol)
    , d_original(original)
    {
    }

    void ensureValidOriginalSymbol()
    {
        symbol_query query{0, d_symbol, nullptr};
        dl_iterate_phdr(&phdr_symfind_callback, (void*)&query);
        auto symbol_addr = reinterpret_cast<signature_t>(query.address);
        if (symbol_addr != nullptr) {
            if (symbol_addr != d_original) {
                LOG(WARNING) << "Correcting symbol for " << d_symbol << " from " << std::hex
                             << reinterpret_cast<void*>(d_original) << " to "
                             << reinterpret_cast<void*>(symbol_addr);
            }
            this->d_original = symbol_addr;
        }
    }

    template<typename... Args>
    auto operator()(Args... args) const noexcept -> decltype(d_original(args...))
    {
        return this->d_original(args...);
    }

    explicit operator bool() const noexcept
    {
        return this->d_original;
    }
};

void
ensureAllHooksAreValid();

enum class Allocator {
    MALLOC = 1,
    FREE = 2,
    CALLOC = 3,
    REALLOC = 4,
    POSIX_MEMALIGN = 5,
    MEMALIGN = 6,
    VALLOC = 7,
    PVALLOC = 8,
    MMAP = 9,
    MUNMAP = 10,
};

enum class AllocatorKind {
    SIMPLE_ALLOCATOR = 1,
    SIMPLE_DEALLOCATOR = 2,
    RANGED_ALLOCATOR = 3,
    RANGED_DEALLOCATOR = 4,
};

AllocatorKind
allocatorKind(const Allocator& allocator);

#define FOR_EACH_HOOKED_FUNCTION(f) extern SymbolHook<decltype(&::f)> f;
PENSIEVE_HOOKED_FUNCTIONS
#undef FOR_EACH_HOOKED_FUNCTION

}  // namespace memray::hooks

namespace memray::intercept {
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

int
prctl(int option, ...) noexcept;

PyGILState_STATE
PyGILState_Ensure() noexcept;

}  // namespace memray::intercept

#endif  //_PENSIEVE_HOOKS_H
