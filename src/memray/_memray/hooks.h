#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <dlfcn.h>
#include <sys/mman.h>
#include <sys/types.h>

#include <cstdlib>
#include <iostream>

#ifdef __linux__
#    include "elf_utils.h"
#    include <malloc.h>
#    include <sys/prctl.h>
#endif

#include "alloc.h"
#include "logging.h"

#if defined(__APPLE__)
#    define MEMRAY_PLATFORM_HOOKED_FUNCTIONS
#elif defined(__GLIBC__)
#    define MEMRAY_PLATFORM_HOOKED_FUNCTIONS                                                            \
        FOR_EACH_HOOKED_FUNCTION(memalign)                                                              \
        FOR_EACH_HOOKED_FUNCTION(prctl)                                                                 \
        FOR_EACH_HOOKED_FUNCTION(pvalloc)                                                               \
        FOR_EACH_HOOKED_FUNCTION(mmap64)
#else
#    define MEMRAY_PLATFORM_HOOKED_FUNCTIONS                                                            \
        FOR_EACH_HOOKED_FUNCTION(memalign)                                                              \
        FOR_EACH_HOOKED_FUNCTION(prctl)
#endif

#define MEMRAY_HOOKED_FUNCTIONS                                                                         \
    FOR_EACH_HOOKED_FUNCTION(malloc)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(free)                                                                      \
    FOR_EACH_HOOKED_FUNCTION(calloc)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(realloc)                                                                   \
    FOR_EACH_HOOKED_FUNCTION(valloc)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(posix_memalign)                                                            \
    FOR_EACH_HOOKED_FUNCTION(aligned_alloc)                                                             \
    FOR_EACH_HOOKED_FUNCTION(mmap)                                                                      \
    FOR_EACH_HOOKED_FUNCTION(munmap)                                                                    \
    FOR_EACH_HOOKED_FUNCTION(dlsym)                                                                     \
    FOR_EACH_HOOKED_FUNCTION(dlclose)                                                                   \
    FOR_EACH_HOOKED_FUNCTION(PyGILState_Ensure)                                                         \
    MEMRAY_PLATFORM_HOOKED_FUNCTIONS

namespace memray::hooks {

struct symbol_query
{
    size_t maps_visited;
    const char* symbol_name;
    void* address;
};

#ifdef __linux__
int
phdr_symfind_callback(dl_phdr_info* info, [[maybe_unused]] size_t size, void* data) noexcept;
#endif

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
#if defined(__linux__)
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
#else
        return;
#endif
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

enum class Allocator : unsigned char {
    MALLOC = 1,
    FREE = 2,
    CALLOC = 3,
    REALLOC = 4,
    POSIX_MEMALIGN = 5,
    ALIGNED_ALLOC = 6,
    MEMALIGN = 7,
    VALLOC = 8,
    PVALLOC = 9,
    MMAP = 10,
    MUNMAP = 11,
    PYMALLOC_MALLOC = 12,
    PYMALLOC_CALLOC = 13,
    PYMALLOC_REALLOC = 14,
    PYMALLOC_FREE = 15,
};

enum class AllocatorKind {
    SIMPLE_ALLOCATOR = 1,
    SIMPLE_DEALLOCATOR = 2,
    RANGED_ALLOCATOR = 3,
    RANGED_DEALLOCATOR = 4,
};

AllocatorKind
allocatorKind(const Allocator& allocator);

bool
isDeallocator(const Allocator& allocator);

#define MEMRAY_ORIG_concat_helper(x, y) x##y
#define MEMRAY_ORIG_NO_NS(f) MEMRAY_ORIG_concat_helper(memray_, f)
#define MEMRAY_ORIG(f) memray::hooks::MEMRAY_ORIG_NO_NS(f)

#define FOR_EACH_HOOKED_FUNCTION(f) extern SymbolHook<decltype(&::f)> MEMRAY_ORIG_NO_NS(f);
MEMRAY_HOOKED_FUNCTIONS
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
aligned_alloc(size_t alignment, size_t size) noexcept;

void*
memalign(size_t alignment, size_t size) noexcept;

void*
valloc(size_t size) noexcept;

void*
pvalloc(size_t size) noexcept;

void*
dlsym(void* handle, const char* symbol) noexcept;

int
dlclose(void* handle) noexcept;

void*
mmap(void* addr, size_t length, int prot, int flags, int fd, off_t offset) noexcept;

#if defined(__GLIBC__)
void*
mmap64(void* addr, size_t length, int prot, int flags, int fd, off64_t offset) noexcept;
#endif

int
munmap(void* addr, size_t length) noexcept;

int
prctl(int option, ...) noexcept;

PyGILState_STATE
PyGILState_Ensure() noexcept;

void*
pymalloc_malloc(void* ctx, size_t size) noexcept;
void*
pymalloc_realloc(void* ctx, void* ptr, size_t new_size) noexcept;
void*
pymalloc_calloc(void* ctx, size_t nelem, size_t size) noexcept;
void
pymalloc_free(void* ctx, void* ptr) noexcept;

}  // namespace memray::intercept
