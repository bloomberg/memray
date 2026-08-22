#include "native_trace_cache.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <libunwind.h>
#include <pthread.h>
#include <stdexcept>
#include <utility>

#include "tracking_api.h"

namespace memray::tracking_api {
namespace {

enum class CacheEntryState {
    EMPTY,
    CANDIDATE,
    REJECTED,
    READY,
};

struct NativeTraceCacheEntry
{
    std::vector<frame_id_t> trace;
    std::vector<const frame_id_t*> return_slots;
    uintptr_t stack_pointer{};
    uint64_t fingerprint{};
    size_t trace_size{};
    CacheEntryState state{};
};

struct NativeTraceCache
{
    std::array<NativeTraceCacheEntry, 8> entries;
    NativeTraceCacheEntry probation;
    size_t next_entry{};
    size_t last_hit{entries.size()};
    uintptr_t stack_low{};
    uintptr_t stack_high{};
    bool stack_bounds_initialized{};
    bool stack_bounds_available{};
};

pthread_key_t s_native_trace_cache_key;
MEMRAY_FAST_TLS thread_local NativeTraceCache* s_native_trace_cache;

__attribute__((noinline)) bool
captureValidationTrace(
        NativeTraceCacheEntry& candidate,
        const std::vector<frame_id_t>& expected,
        size_t expected_size,
        uintptr_t stack_low,
        uintptr_t stack_high)
{
    unw_context_t context;
    unw_cursor_t cursor;
    if (unw_getcontext(&context) < 0 || unw_init_local(&cursor, &context) < 0) {
        return false;
    }

    candidate.return_slots.clear();
    candidate.return_slots.reserve(
            expected_size > NATIVE_TRACE_CACHE_INTERNAL_FRAMES
                    ? expected_size - NATIVE_TRACE_CACHE_INTERNAL_FRAMES
                    : 0);
    for (size_t index = 0; index <= expected_size; ++index) {
        unw_word_t ip;
        if (unw_get_reg(&cursor, UNW_REG_IP, &ip) < 0) {
            return false;
        }

        // expected[0] is captureNativeTrace, but its IP differs depending on
        // whether it called this helper or unw_backtrace.
        if (index > NATIVE_TRACE_CACHE_INTERNAL_FRAMES) {
            if (ip != expected[index - NATIVE_TRACE_CACHE_INTERNAL_FRAMES]) {
                return false;
            }
            unw_save_loc_t location;
            if (unw_is_signal_frame(&cursor) != 0 || unw_get_save_loc(&cursor, UNW_REG_IP, &location) < 0
                || location.type != UNW_SLT_MEMORY)
            {
                return false;
            }

            const uintptr_t address = location.u.addr;
            if (address % alignof(frame_id_t) != 0 || address < stack_low || stack_high < stack_low
                || stack_high - stack_low < sizeof(frame_id_t)
                || address > stack_high - sizeof(frame_id_t))
            {
                return false;
            }

            const auto* return_slot = reinterpret_cast<const frame_id_t*>(address);
            if (__atomic_load_n(return_slot, __ATOMIC_RELAXED) != ip) {
                return false;
            }
            candidate.return_slots.push_back(return_slot);
        }

        const int step_result = unw_step(&cursor);
        if (step_result == 0) {
            return index == expected_size;
        }
        if (step_result < 0) {
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

    cache.stack_low = reinterpret_cast<uintptr_t>(stack_address);
    cache.stack_high = cache.stack_low + stack_size;
    cache.stack_bounds_available = true;
    return true;
}

NativeTraceCacheEntry*
findTrainingEntry(
        NativeTraceCache& cache,
        uintptr_t stack_pointer,
        uint64_t fingerprint,
        size_t trace_size)
{
    for (NativeTraceCacheEntry& entry : cache.entries) {
        if ((entry.state == CacheEntryState::CANDIDATE || entry.state == CacheEntryState::REJECTED)
            && entry.stack_pointer == stack_pointer && entry.fingerprint == fingerprint
            && entry.trace_size == trace_size)
        {
            return &entry;
        }
    }
    NativeTraceCacheEntry& probation = cache.probation;
    if ((probation.state == CacheEntryState::CANDIDATE || probation.state == CacheEntryState::REJECTED)
        && probation.stack_pointer == stack_pointer && probation.fingerprint == fingerprint
        && probation.trace_size == trace_size)
    {
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
    if (cache.last_hit < cache.entries.size()
        && matchesCachedTrace(cache.entries[cache.last_hit], stack_pointer))
    {
        return &cache.entries[cache.last_hit];
    }
    for (size_t index = 0; index < cache.entries.size(); ++index) {
        if (index != cache.last_hit && matchesCachedTrace(cache.entries[index], stack_pointer)) {
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
    uint64_t fingerprint = 1469598103934665603ULL;
    for (size_t index = NATIVE_TRACE_CACHE_INTERNAL_FRAMES; index < size; ++index) {
        fingerprint ^= trace[index];
        fingerprint *= 1099511628211ULL;
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
        return unw_backtrace((void**)frames.data(), frames.size());
    }
    NativeTraceCache& cache = *cache_ptr;

    // Matching the stack pointer is not enough: different callers can reuse it.
    if (const NativeTraceCacheEntry* cached = findCachedTrace(cache, stack_pointer)) {
        std::copy(cached->trace.begin(), cached->trace.end(), frames.begin());
        return cached->trace.size();
    }

    const size_t size = unw_backtrace((void**)frames.data(), frames.size());
    if (size >= frames.size()) {
        return size;
    }
    const uint64_t fingerprint = traceFingerprint(frames.data(), size);
    // Finding saved-register locations costs another unwind, so wait for a trace
    // to repeat before training it.
    NativeTraceCacheEntry* candidate = findTrainingEntry(cache, stack_pointer, fingerprint, size);
    if (candidate && candidate->state == CacheEntryState::REJECTED) {
        return size;
    }
    if (candidate) {
        candidate->state = CacheEntryState::REJECTED;
        if (initializeStackBounds(cache)) {
            const bool cacheable =
                    captureValidationTrace(*candidate, frames, size, cache.stack_low, cache.stack_high);
            if (cacheable && size
                && candidate->return_slots.size() + NATIVE_TRACE_CACHE_INTERNAL_FRAMES == size)
            {
                candidate->trace.assign(frames.begin(), frames.begin() + size);
                if (candidate == &cache.probation) {
                    size_t victim_index = cache.next_entry;
                    if (victim_index == cache.last_hit) {
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
    s_native_trace_cache->last_hit = s_native_trace_cache->entries.size();
}

}  // namespace memray::tracking_api
