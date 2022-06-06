#include <cassert>
#include <cstdio>

#include "hooks.h"
#include "tracking_api.h"

namespace memray {
namespace {  // unnamed

class BernoulliSampler
{
  public:
    // Methods
    BernoulliSampler();
    void setSamplingInterval(size_t sampling_interval);
    size_t getSamplingInterval();
    size_t calculateSampleSize(size_t size);

  private:
    // Methods
    size_t poissonStep();

    // Data members
    size_t d_sampling_interval_in_bytes;
    double d_sampling_probability;
    std::atomic<size_t> d_bytes_until_next_sample;
};

BernoulliSampler::BernoulliSampler()
{
    setSamplingInterval(1);
}

void
BernoulliSampler::setSamplingInterval(size_t sampling_interval)
{
    d_sampling_interval_in_bytes = sampling_interval;
    d_sampling_probability = 1.0 / d_sampling_interval_in_bytes;
    d_bytes_until_next_sample = poissonStep();
}

size_t
BernoulliSampler::getSamplingInterval()
{
    return d_sampling_interval_in_bytes;
}

size_t
BernoulliSampler::calculateSampleSize(size_t size)
{
    if (size >= d_sampling_interval_in_bytes) {
        return size;
    }

    size_t n_samples = 0;
    size_t next_step = 0;
    while (size) {
        size_t loaded_bytes_until_next_sample =
                d_bytes_until_next_sample.load(std::memory_order::memory_order_relaxed);
        if (size >= loaded_bytes_until_next_sample) {
            // We're being sampled! We need to replace our atomic entirely.
            // Randomly decide when to stop next, if we haven't already.
            if (!next_step) {
                next_step = poissonStep();
            }

            if (!d_bytes_until_next_sample.compare_exchange_weak(
                        loaded_bytes_until_next_sample,
                        next_step,
                        std::memory_order::memory_order_relaxed))
            {
                continue;  // Didn't update the atomic; loop and try again.
            }

            // Successfully updated the atomic; some bytes are accounted for.
            next_step = 0;  // Our random number has been used
            size -= loaded_bytes_until_next_sample;
            n_samples++;
        } else {
            // We're not being sampled; just decrement our atomic.
            if (!d_bytes_until_next_sample.compare_exchange_weak(
                        loaded_bytes_until_next_sample,
                        loaded_bytes_until_next_sample - size,
                        std::memory_order::memory_order_relaxed))
            {
                continue;  // Didn't update the atomic; loop and try again.
            }

            // Successfully updated the atomic; all bytes are accounted for.
            size = 0;
        }
    }

    return d_sampling_interval_in_bytes * n_samples;
}

size_t
BernoulliSampler::poissonStep()
{
    static_assert(std::is_trivially_destructible<std::default_random_engine>::value);
    static thread_local std::default_random_engine s_random_engine;
    std::exponential_distribution<double> exponential_dist(d_sampling_probability);
    return static_cast<size_t>(exponential_dist(s_random_engine)) + 1;
}

static BernoulliSampler s_sampler;

}  // unnamed namespace

namespace hooks {

void
setSamplingInterval(size_t sampling_interval)
{
    s_sampler.setSamplingInterval(sampling_interval);
}

size_t
getSamplingInterval()
{
    return s_sampler.getSamplingInterval();
}

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

}  // namespace hooks

namespace intercept {

static constexpr size_t MEMRAY_ALLOC_OVERHEAD = 1;
static constexpr char TRACE_MARK = 42;

static inline void
sampleAllocation(void* ptr, size_t size, hooks::Allocator allocator)
{
    if (!ptr) {
        return;
    }

    if (s_sampler.getSamplingInterval() <= 1) {
        tracking_api::Tracker::trackAllocation(ptr, size, allocator);
    } else if (size_t sampled_size = s_sampler.calculateSampleSize(size)) {
        size_t usable_size = malloc_usable_size(ptr);
        static_cast<char*>(ptr)[usable_size - 1] = TRACE_MARK;
        tracking_api::Tracker::trackAllocation(ptr, sampled_size, allocator);
    }
}

static inline bool
ptrWasSampled(void* ptr)
{
    if (ptr == nullptr) {
        return false;
    }
    if (s_sampler.getSamplingInterval() <= 1) {
        return true;
    }
    size_t usable_size = malloc_usable_size(ptr);
    return static_cast<char*>(ptr)[usable_size - 1] == TRACE_MARK;
}

void*
pymalloc_malloc(void* ctx, size_t size) noexcept
{
    PyMemAllocatorEx* alloc = (PyMemAllocatorEx*)ctx;
    void* ptr = nullptr;
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
    PyMemAllocatorEx* alloc = (PyMemAllocatorEx*)ctx;
    void* ret = nullptr;
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
    PyMemAllocatorEx* alloc = (PyMemAllocatorEx*)ctx;
    void* ptr = nullptr;
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
    PyMemAllocatorEx* alloc = (PyMemAllocatorEx*)ctx;
    {
        tracking_api::RecursionGuard guard;
        alloc->free(alloc->ctx, ptr);
    }
    if (ptr) {
        tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::PYMALLOC_FREE);
    }
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
malloc(size_t size) noexcept
{
    assert(hooks::malloc);

    void* ptr = hooks::malloc(size + MEMRAY_ALLOC_OVERHEAD);
    sampleAllocation(ptr, size, hooks::Allocator::MALLOC);
    return ptr;
}

void
free(void* ptr) noexcept
{
    assert(hooks::free);

    // We need to call our API before we call the real free implementation
    // to make sure that the pointer is not reused in-between.
    if (ptrWasSampled(ptr)) {
        tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::FREE);
    }

    hooks::free(ptr);
}

void*
realloc(void* ptr, size_t size) noexcept
{
    assert(hooks::realloc);

    bool ptr_was_sampled = ptrWasSampled(ptr);
    void* ret = hooks::realloc(ptr, size + MEMRAY_ALLOC_OVERHEAD);
    if (ret) {
        if (ptr_was_sampled) {
            tracking_api::Tracker::trackDeallocation(ptr, 0, hooks::Allocator::FREE);
        }
        sampleAllocation(ret, size, hooks::Allocator::REALLOC);
    }
    return ret;
}

void*
calloc(size_t num, size_t size) noexcept
{
    assert(hooks::calloc);

    void* ret = hooks::calloc(num, size + MEMRAY_ALLOC_OVERHEAD);
    sampleAllocation(ret, num * size, hooks::Allocator::CALLOC);
    return ret;
}

int
posix_memalign(void** memptr, size_t alignment, size_t size) noexcept
{
    assert(hooks::posix_memalign);

    int ret = hooks::posix_memalign(memptr, alignment, size + MEMRAY_ALLOC_OVERHEAD);
    if (!ret) {
        sampleAllocation(*memptr, size, hooks::Allocator::POSIX_MEMALIGN);
    }
    return ret;
}

void*
aligned_alloc(size_t alignment, size_t size) noexcept
{
    assert(hooks::aligned_alloc);

    // The **size** parameter has the added restriction that size should be a multiple of alignment
    // so we need to account for this when adding the overhead.
    assert(alignment > 0 && 0 == (alignment & (alignment - 1)));  // alignment must be a power of 2
    size_t padded_size = (size + MEMRAY_ALLOC_OVERHEAD + alignment - 1) & -alignment;
    void* ret = hooks::aligned_alloc(alignment, padded_size);
    sampleAllocation(ret, size, hooks::Allocator::ALIGNED_ALLOC);
    return ret;
}

void*
memalign(size_t alignment, size_t size) noexcept
{
    assert(hooks::memalign);

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::memalign(alignment, size + MEMRAY_ALLOC_OVERHEAD);
    }
    sampleAllocation(ret, size, hooks::Allocator::MEMALIGN);
    return ret;
}

void*
valloc(size_t size) noexcept
{
    assert(hooks::valloc);

    void* ret;
    {
        tracking_api::RecursionGuard guard;
        ret = hooks::valloc(size + MEMRAY_ALLOC_OVERHEAD);
    }
    sampleAllocation(ret, size, hooks::Allocator::VALLOC);
    return ret;
}

#if defined(__GLIBC__)
void*
pvalloc(size_t size) noexcept
{
    assert(hooks::pvalloc);

    void* ret = hooks::pvalloc(size + MEMRAY_ALLOC_OVERHEAD);
    sampleAllocation(ret, size, hooks::Allocator::PVALLOC);
    return ret;
}
#endif

void*
dlopen(const char* filename, int flag) noexcept
{
    assert(hooks::dlopen);

    void* ret = hooks::dlopen(filename, flag);
    if (ret) tracking_api::Tracker::invalidate_module_cache();
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

PyGILState_STATE
PyGILState_Ensure() noexcept
{
    PyGILState_STATE ret = hooks::PyGILState_Ensure();
    tracking_api::install_trace_function();
    return ret;
}

}  // namespace intercept
}  // namespace memray
