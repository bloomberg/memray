#include "native_trace_cache.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <libunwind.h>
#include <limits>
#include <optional>
#include <pthread.h>
#include <stdexcept>
#include <utility>

#include "tracking_api.h"

namespace memray::tracking_api {
namespace {

constexpr size_t NATIVE_TRACE_CACHE_CAPACITY = 8;
constexpr uint64_t FNV1A_OFFSET_BASIS = 14695981039346656037ULL;
constexpr uint64_t FNV1A_PRIME = 1099511628211ULL;

enum class CacheEntryState {
    EMPTY,
    CANDIDATE,
    REJECTED,
    READY,
};

struct NativeTraceCacheEntry
{
    CacheEntryState state{CacheEntryState::EMPTY};
    uintptr_t stack_pointer{};
    uint64_t fingerprint{};
    size_t trace_size{};
    std::vector<frame_id_t> trace;
    std::vector<const frame_id_t*> return_slots;
};

struct StackBounds
{
    uintptr_t low{};
    uintptr_t high{};

    bool contains(uintptr_t address) const
    {
        return high >= low && high - low >= sizeof(frame_id_t) && address >= low
               && address <= high - sizeof(frame_id_t) && address % alignof(frame_id_t) == 0;
    }
};

struct NativeTraceCache
{
    std::array<NativeTraceCacheEntry, NATIVE_TRACE_CACHE_CAPACITY> entries;
    NativeTraceCacheEntry probation;
    size_t next_entry{};
    std::optional<size_t> last_hit;
    StackBounds stack_bounds;
    bool stack_bounds_initialized{};
    bool stack_bounds_available{};
};

pthread_key_t s_native_trace_cache_key;
MEMRAY_FAST_TLS thread_local NativeTraceCache* s_native_trace_cache;

__attribute__((noinline)) bool
captureReturnSlots(
        std::vector<const frame_id_t*>& return_slots,
        const std::vector<frame_id_t>& expected,
        size_t expected_size,
        const StackBounds& stack_bounds)
{
    unw_context_t context;
    unw_cursor_t cursor;
    if (expected_size <= NATIVE_TRACE_CACHE_INTERNAL_FRAMES || unw_getcontext(&context) < 0
        || unw_init_local(&cursor, &context) < 0)
    {
        return false;
    }

    return_slots.clear();
    return_slots.reserve(expected_size - NATIVE_TRACE_CACHE_INTERNAL_FRAMES);

    // This helper adds one frame. Advance past it and the cached capture frame
    // to the first caller that is present in both traces.
    for (size_t index = 0; index <= NATIVE_TRACE_CACHE_INTERNAL_FRAMES; ++index) {
        if (unw_step(&cursor) <= 0) {
            return false;
        }
    }

    for (size_t index = NATIVE_TRACE_CACHE_INTERNAL_FRAMES; index < expected_size; ++index) {
        unw_word_t ip;
        if (unw_get_reg(&cursor, UNW_REG_IP, &ip) < 0) {
            return false;
        }
        if (ip != expected[index]) {
            return false;
        }

        unw_save_loc_t location{};
        if (unw_is_signal_frame(&cursor) != 0 || unw_get_save_loc(&cursor, UNW_REG_IP, &location) < 0
            || location.type != UNW_SLT_MEMORY || !stack_bounds.contains(location.u.addr))
        {
            return false;
        }

        const auto* return_slot = reinterpret_cast<const frame_id_t*>(location.u.addr);
        if (__atomic_load_n(return_slot, __ATOMIC_RELAXED) != ip) {
            return false;
        }
        return_slots.push_back(return_slot);

        const int step_result = unw_step(&cursor);
        if (index + 1 == expected_size) {
            return step_result == 0;
        }
        if (step_result <= 0) {
            return false;
        }
    }
    return false;
}

uintptr_t
currentStackPointer()
{
    uintptr_t stack_pointer;
    asm("mov %%rsp, %0" : "=r"(stack_pointer));
    return stack_pointer;
}

bool
initializeStackBounds(NativeTraceCache& cache)
{
    if (cache.stack_bounds_initialized) {
        return cache.stack_bounds_available;
    }
    cache.stack_bounds_initialized = true;

    pthread_attr_t attributes;
    if (pthread_getattr_np(pthread_self(), &attributes)) {
        return false;
    }

    void* stack_address = nullptr;
    size_t stack_size = 0;
    const bool success = !pthread_attr_getstack(&attributes, &stack_address, &stack_size);
    pthread_attr_destroy(&attributes);
    if (!success) {
        return false;
    }

    const uintptr_t stack_low = reinterpret_cast<uintptr_t>(stack_address);
    if (stack_size > std::numeric_limits<uintptr_t>::max() - stack_low) {
        return false;
    }
    cache.stack_bounds = {stack_low, stack_low + stack_size};
    cache.stack_bounds_available = true;
    return true;
}

bool
matchesTraceIdentity(
        const NativeTraceCacheEntry& entry,
        uintptr_t stack_pointer,
        uint64_t fingerprint,
        size_t trace_size)
{
    const bool has_identity =
            entry.state == CacheEntryState::CANDIDATE || entry.state == CacheEntryState::REJECTED;
    return has_identity && entry.stack_pointer == stack_pointer && entry.fingerprint == fingerprint
           && entry.trace_size == trace_size;
}

NativeTraceCacheEntry*
findTraceEntry(NativeTraceCache& cache, uintptr_t stack_pointer, uint64_t fingerprint, size_t trace_size)
{
    for (NativeTraceCacheEntry& entry : cache.entries) {
        if (matchesTraceIdentity(entry, stack_pointer, fingerprint, trace_size)) {
            return &entry;
        }
    }
    NativeTraceCacheEntry& probation = cache.probation;
    if (matchesTraceIdentity(probation, stack_pointer, fingerprint, trace_size)) {
        return &probation;
    }
    return nullptr;
}

NativeTraceCacheEntry&
nextCandidateEntry(NativeTraceCache& cache)
{
    for (size_t offset = 0; offset < cache.entries.size(); ++offset) {
        const size_t index = (cache.next_entry + offset) % cache.entries.size();
        if (cache.entries[index].state != CacheEntryState::READY) {
            cache.next_entry = (index + 1) % cache.entries.size();
            return cache.entries[index];
        }
    }

    return cache.probation;
}

bool
matchesCachedTrace(const NativeTraceCacheEntry& entry, uintptr_t stack_pointer)
{
    return entry.state == CacheEntryState::READY && entry.stack_pointer == stack_pointer
           && entry.return_slots.size() + NATIVE_TRACE_CACHE_INTERNAL_FRAMES == entry.trace.size()
           && std::equal(
                   entry.return_slots.begin(),
                   entry.return_slots.end(),
                   entry.trace.begin() + NATIVE_TRACE_CACHE_INTERNAL_FRAMES,
                   [](const frame_id_t* slot, frame_id_t ip) {
                       return __atomic_load_n(slot, __ATOMIC_RELAXED) == ip;
                   });
}

const NativeTraceCacheEntry*
findCachedTrace(NativeTraceCache& cache, uintptr_t stack_pointer)
{
    if (cache.last_hit && matchesCachedTrace(cache.entries[*cache.last_hit], stack_pointer)) {
        return &cache.entries[*cache.last_hit];
    }
    for (size_t index = 0; index < cache.entries.size(); ++index) {
        if (cache.last_hit != index && matchesCachedTrace(cache.entries[index], stack_pointer)) {
            cache.last_hit = index;
            return &cache.entries[index];
        }
    }
    return nullptr;
}

NativeTraceCache*
nativeTraceCache()
{
    if (!s_native_trace_cache) {
        s_native_trace_cache =
                static_cast<NativeTraceCache*>(pthread_getspecific(s_native_trace_cache_key));
        if (!s_native_trace_cache) {
            s_native_trace_cache = new NativeTraceCache;
            if (pthread_setspecific(s_native_trace_cache_key, s_native_trace_cache)) {
                delete s_native_trace_cache;
                s_native_trace_cache = nullptr;
                Tracker::deactivate();
                fprintf(stderr, "memray: pthread_setspecific failed for native trace cache\n");
            }
        }
    }
    return s_native_trace_cache;
}

uint64_t
traceFingerprint(const frame_id_t* trace, size_t size)
{
    uint64_t fingerprint = FNV1A_OFFSET_BASIS;
    for (size_t index = NATIVE_TRACE_CACHE_INTERNAL_FRAMES; index < size; ++index) {
        fingerprint ^= trace[index];
        fingerprint *= FNV1A_PRIME;
    }
    return fingerprint;
}

}  // namespace

__attribute__((noinline)) size_t
captureNativeTrace(std::vector<frame_id_t>& frames)
{
    const uintptr_t stack_pointer = currentStackPointer();
    NativeTraceCache* cache_ptr = nativeTraceCache();
    if (!cache_ptr) {
        return unw_backtrace(reinterpret_cast<void**>(frames.data()), frames.size());
    }
    NativeTraceCache& cache = *cache_ptr;

    // Matching the stack pointer is not enough: different callers can reuse it.
    if (const NativeTraceCacheEntry* cached = findCachedTrace(cache, stack_pointer)) {
        std::copy(cached->trace.begin(), cached->trace.end(), frames.begin());
        return cached->trace.size();
    }

    const size_t size = unw_backtrace(reinterpret_cast<void**>(frames.data()), frames.size());
    if (size >= frames.size()) {
        return size;
    }
    const uint64_t fingerprint = traceFingerprint(frames.data(), size);
    // Finding saved-register locations costs another unwind, so wait for a trace
    // to repeat before training it.
    NativeTraceCacheEntry* candidate = findTraceEntry(cache, stack_pointer, fingerprint, size);
    if (candidate && candidate->state == CacheEntryState::REJECTED) {
        return size;
    }
    if (candidate) {
        candidate->state = CacheEntryState::REJECTED;
        if (initializeStackBounds(cache)) {
            const bool cacheable =
                    captureReturnSlots(candidate->return_slots, frames, size, cache.stack_bounds);
            if (cacheable && size
                && candidate->return_slots.size() + NATIVE_TRACE_CACHE_INTERNAL_FRAMES == size)
            {
                candidate->trace.assign(frames.begin(), frames.begin() + size);
                if (candidate == &cache.probation) {
                    size_t victim_index = cache.next_entry;
                    if (cache.last_hit && victim_index == *cache.last_hit) {
                        victim_index = (victim_index + 1) % cache.entries.size();
                    }
                    cache.next_entry = (victim_index + 1) % cache.entries.size();
                    NativeTraceCacheEntry& victim = cache.entries[victim_index];
                    std::swap(victim, *candidate);
                    cache.probation.state = CacheEntryState::EMPTY;
                    candidate = &victim;
                }
                candidate->state = CacheEntryState::READY;
            }
        }
    } else {
        NativeTraceCacheEntry& new_candidate = nextCandidateEntry(cache);
        new_candidate.state = CacheEntryState::CANDIDATE;
        new_candidate.stack_pointer = stack_pointer;
        new_candidate.fingerprint = fingerprint;
        new_candidate.trace_size = size;
    }
    return size;
}

void
setupNativeTraceCache()
{
    if (pthread_key_create(&s_native_trace_cache_key, [](void* data) {
            RecursionGuard guard;
            s_native_trace_cache = nullptr;
            delete static_cast<NativeTraceCache*>(data);
        }))
    {
        throw std::runtime_error{"Failed to create native trace cache key"};
    }
}

void
flushNativeTraceCache()
{
    if (!s_native_trace_cache) {
        return;
    }
    for (auto& entry : s_native_trace_cache->entries) {
        entry.state = CacheEntryState::EMPTY;
    }
    s_native_trace_cache->probation.state = CacheEntryState::EMPTY;
    s_native_trace_cache->last_hit.reset();
}

}  // namespace memray::tracking_api
