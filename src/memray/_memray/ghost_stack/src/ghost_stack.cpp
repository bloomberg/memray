/**
 * GhostStack Implementation
 * =========================
 * Shadow stack-based fast unwinding with O(1) cached captures.
 */

#include "ghost_stack.h"

#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cxxabi.h>
#include <mutex>
#include <pthread.h>
#include <vector>

#define UNW_LOCAL_ONLY
#include <libunwind.h>

#ifdef __APPLE__
#include <execinfo.h>
#endif

// Assembly trampoline (defined in *_trampoline.s)
// The 'used' attribute prevents LTO from stripping the symbol and its eh_frame data
extern "C" void ghost_ret_trampoline();
extern "C" void ghost_ret_trampoline_start();

// Force references to trampoline symbols to prevent LTO from stripping eh_frame
// These are never called, just referenced to keep the symbols alive
__attribute__((used)) static void* const _ghost_trampoline_refs[] = {
    reinterpret_cast<void*>(&ghost_ret_trampoline),
    reinterpret_cast<void*>(&ghost_ret_trampoline_start),
};

// ============================================================================
// Platform Configuration
// ============================================================================

#if defined(__aarch64__) || defined(__arm64__)
    #define GS_ARCH_AARCH64 1
    #define GS_SP_REGISTER UNW_AARCH64_X29
    #define GS_RA_REGISTER UNW_AARCH64_X30
#elif defined(__x86_64__)
    #define GS_ARCH_X86_64 1
    #define GS_SP_REGISTER UNW_X86_64_RBP
    #define GS_RA_REGISTER UNW_X86_64_RIP
#else
    #error "Unsupported architecture"
#endif

#ifndef GHOST_STACK_MAX_FRAMES
#define GHOST_STACK_MAX_FRAMES 512
#endif

// ============================================================================
// Logging (minimal, stderr only)
// ============================================================================

// GS_FORCE_DEBUG can be defined via compiler flag (-DGS_FORCE_DEBUG) for test builds
#if defined(DEBUG) || defined(GS_FORCE_DEBUG)
#define LOG_DEBUG(...) do { fprintf(stderr, "[GhostStack][DEBUG] " __VA_ARGS__); fflush(stderr); } while(0)
#else
#define LOG_DEBUG(...) ((void)0)
#endif

#define LOG_ERROR(...) do { fprintf(stderr, "[GhostStack][ERROR] " __VA_ARGS__); fflush(stderr); } while(0)
#define LOG_INFO(...) do { fprintf(stderr, "[GhostStack][INFO] " __VA_ARGS__); fflush(stderr); } while(0)

// ============================================================================
// Utilities
// ============================================================================

#ifdef GS_ARCH_AARCH64
static inline uintptr_t ptrauth_strip(uintptr_t val) {
    uint64_t ret;
    asm volatile(
        "mov x30, %1\n\t"
        "xpaclri\n\t"
        "mov %0, x30\n\t"
        : "=r"(ret) : "r"(val) : "x30");
    return ret;
}
#else
static inline uintptr_t ptrauth_strip(uintptr_t val) { return val; }
#endif

// ============================================================================
// Stack Entry
// ============================================================================

struct StackEntry {
    uintptr_t ip;               // Instruction pointer of this frame (what to return to caller)
    uintptr_t return_address;   // Original return address (what we replaced with trampoline)
    uintptr_t* location;        // Where it lives on the stack
    uintptr_t stack_pointer;    // SP at capture time (for validation)
};

// ============================================================================
// GhostStack Core (thread-local)
// ============================================================================

class GhostStackImpl {
public:
    GhostStackImpl() {
        entries_.reserve(64);
    }

    ~GhostStackImpl() {
        reset();
    }

    // Set custom unwinder (NULL = use default libunwind)
    void set_unwinder(ghost_stack_unwinder_t unwinder) {
        custom_unwinder_ = unwinder;
    }

    // Main capture function - returns number of frames
    size_t backtrace(void** buffer, size_t max_frames) {
        LOG_DEBUG("=== backtrace ENTER ===\n");
        LOG_DEBUG("  this=%p, buffer=%p, max_frames=%zu\n", (void*)this, (void*)buffer, max_frames);
        LOG_DEBUG("  is_capturing_=%d, trampolines_installed_=%d, entries_.size()=%zu, tail_=%zu\n",
                  (int)is_capturing_, (int)trampolines_installed_, entries_.size(),
                  tail_.load(std::memory_order_acquire));

        if (is_capturing_) {
            LOG_DEBUG("  Recursive call detected, returning 0\n");
            return 0;  // Recursive call, bail out
        }
        is_capturing_ = true;

        size_t result = 0;

        // Fast path: trampolines installed, return cached frames
        if (trampolines_installed_ && !entries_.empty()) {
            LOG_DEBUG("  Taking FAST PATH (cached frames)\n");
            result = copy_cached_frames(buffer, max_frames);
            is_capturing_ = false;
            LOG_DEBUG("=== backtrace EXIT (fast path) result=%zu ===\n", result);
            return result;
        }

        // Slow path: capture with unwinder and install trampolines
        LOG_DEBUG("  Taking SLOW PATH (capture and install)\n");

        // Clear any stale entries from a previous reset before starting fresh capture
        if (!entries_.empty() && !trampolines_installed_) {
            LOG_DEBUG("  Clearing %zu stale entries from previous reset\n", entries_.size());
            entries_.clear();
            tail_.store(0, std::memory_order_release);
        }

        result = capture_and_install(buffer, max_frames);
        is_capturing_ = false;
        LOG_DEBUG("=== backtrace EXIT (slow path) result=%zu ===\n", result);
        return result;
    }

    /**
     * Reset the shadow stack, restoring all original return addresses.
     *
     * On ARM64, stale trampolines may still fire after reset() because the LR
     * register may have already been loaded with the trampoline address before
     * we restored the stack location. We keep entries_ around to handle these
     * stale trampolines gracefully.
     *
     * We restore ALL entries (not just 0 to tail-1) but only if the location
     * still contains the trampoline address. This handles the case where a
     * location was reused by a new frame after its original trampoline fired.
     */
    void reset() {
        LOG_DEBUG("=== reset ENTER ===\n");
        LOG_DEBUG("  this=%p, trampolines_installed_=%d, entries_.size()=%zu, tail_=%zu\n",
                  (void*)this, (int)trampolines_installed_, entries_.size(),
                  tail_.load(std::memory_order_acquire));

        if (trampolines_installed_) {
            uintptr_t tramp_addr = reinterpret_cast<uintptr_t>(ghost_ret_trampoline);
            LOG_DEBUG("  Restoring locations that still have trampoline (0x%lx)\n", (unsigned long)tramp_addr);

            // Restore ALL entries whose locations still contain the trampoline.
            // This handles both pending entries AND already-fired entries whose
            // locations haven't been reused by new frames.
            for (size_t i = 0; i < entries_.size(); ++i) {
                uintptr_t current_value = *entries_[i].location;
                // Strip PAC bits before comparison - on ARM64 with PAC enabled,
                // the value read from stack may be PAC-signed while tramp_addr is not
                uintptr_t stripped_value = ptrauth_strip(current_value);
                if (stripped_value == tramp_addr) {
                    LOG_DEBUG("    [%zu] location=%p, restoring 0x%lx\n",
                              i, (void*)entries_[i].location, (unsigned long)entries_[i].return_address);
                    *entries_[i].location = entries_[i].return_address;
                } else {
                    LOG_DEBUG("    [%zu] location=%p, skipping (current=0x%lx, not trampoline)\n",
                              i, (void*)entries_[i].location, (unsigned long)current_value);
                }
            }

            // Mark trampolines as not installed, but DON'T clear entries_!
            // On ARM64, stale trampolines may still fire because LR was loaded
            // before we restored the stack. Keep entries_ so we can still
            // return the correct address.
            trampolines_installed_ = false;

            // Increment epoch to signal state change
            epoch_.fetch_add(1, std::memory_order_release);
            LOG_DEBUG("  New epoch=%lu (entries preserved for stale trampolines)\n",
                      (unsigned long)epoch_.load(std::memory_order_acquire));
        }
        LOG_DEBUG("=== reset EXIT ===\n");
    }

public:
    /**
     * Direct entry access method for exception handling.
     * Decrements tail and returns the return address without longjmp checking.
     */
    uintptr_t pop_entry() {
        LOG_DEBUG("=== pop_entry ENTER ===\n");
        LOG_DEBUG("  this=%p, entries_.size()=%zu, tail_=%zu\n",
                  (void*)this, entries_.size(), tail_.load(std::memory_order_acquire));

        size_t tail = tail_.fetch_sub(1, std::memory_order_acq_rel) - 1;
        LOG_DEBUG("  After fetch_sub: tail=%zu\n", tail);

        if (tail >= entries_.size()) {
            LOG_ERROR("Stack corruption in pop_entry!\n");
            LOG_ERROR("  tail=%zu, entries_.size()=%zu\n", tail, entries_.size());
            std::abort();
        }
        uintptr_t ret = entries_[tail].return_address;
        LOG_DEBUG("  Returning address 0x%lx\n", (unsigned long)ret);
        LOG_DEBUG("=== pop_entry EXIT ===\n");
        return ret;
    }

private:
    /**
     * Internal helper to clear all state.
     * Increments epoch to invalidate any in-flight trampoline operations.
     */
    void clear_entries() {
        LOG_DEBUG("=== clear_entries ENTER ===\n");
        LOG_DEBUG("  this=%p, entries_.size()=%zu, tail_=%zu, epoch_=%lu\n",
                  (void*)this, entries_.size(), tail_.load(std::memory_order_acquire),
                  (unsigned long)epoch_.load(std::memory_order_acquire));

        // Increment epoch FIRST to signal any in-flight operations
        epoch_.fetch_add(1, std::memory_order_release);
        LOG_DEBUG("  New epoch=%lu\n", (unsigned long)epoch_.load(std::memory_order_acquire));

        entries_.clear();
        tail_.store(0, std::memory_order_release);
        trampolines_installed_ = false;
        LOG_DEBUG("=== clear_entries EXIT ===\n");
    }

public:

    /**
     * Called by trampoline when a function returns.
     *
     * Handles three scenarios:
     * 1. Normal operation: trampolines installed, decrement tail and return
     * 2. Post-reset stale trampoline (ARM64): search entries by SP, don't modify state
     * 3. Longjmp detection: SP mismatch, search backward for matching entry
     *
     * @param sp  Stack pointer at return time (for longjmp detection / entry lookup)
     * @return    Original return address to jump to
     */
    uintptr_t on_ret_trampoline(uintptr_t sp) {
        LOG_DEBUG("=== on_ret_trampoline ENTER ===\n");
        LOG_DEBUG("  this=%p, sp=0x%lx\n", (void*)this, (unsigned long)sp);

        // Log state
        size_t tail_before = tail_.load(std::memory_order_acquire);
        size_t entries_size = entries_.size();
        LOG_DEBUG("  BEFORE: tail_=%zu, entries_.size()=%zu, trampolines_installed_=%d\n",
                  tail_before, entries_size, (int)trampolines_installed_);

        // =========================================================
        // POST-RESET STALE TRAMPOLINE HANDLING (ARM64)
        // =========================================================
        // On ARM64, reset() may have been called but stale trampolines can still
        // fire because LR was loaded before we restored the stack location.
        // In this case, trampolines_installed_ is false but entries_ still has data.
        //
        // Stale trampolines fire in predictable order: the deepest pending frame
        // (highest index that wasn't consumed) fires first, then the next one up.
        // We simply return entries in order starting from tail_-1 and decrementing.
        if (!trampolines_installed_ && !entries_.empty()) {
            size_t current_tail = tail_.load(std::memory_order_acquire);
            LOG_DEBUG("  POST-RESET stale trampoline! tail_=%zu, entries_.size()=%zu\n",
                      current_tail, entries_.size());

            if (current_tail > 0 && current_tail <= entries_.size()) {
                // Return the entry at tail-1 (the deepest pending entry)
                size_t idx = current_tail - 1;
                uintptr_t ret = entries_[idx].return_address;

                // Decrement tail_ for the next stale trampoline (if any)
                tail_.store(idx, std::memory_order_release);

                LOG_DEBUG("  Returning entry[%zu].return_address=0x%lx\n", idx, (unsigned long)ret);
                LOG_DEBUG("=== on_ret_trampoline EXIT (post-reset) ===\n");
                return ret;
            }

            // tail_ is 0 or invalid - this shouldn't happen
            LOG_ERROR("POST-RESET trampoline: tail_=%zu is invalid!\n", current_tail);
            LOG_ERROR("  entries_.size()=%zu\n", entries_.size());
            std::abort();
        }

        // =========================================================
        // NORMAL OPERATION
        // =========================================================
        // Capture current epoch - if it changes during execution, reset() was called
        uint64_t current_epoch = epoch_.load(std::memory_order_acquire);
        LOG_DEBUG("  current_epoch=%lu\n", (unsigned long)current_epoch);

        // Decrement tail first, like nwind does
        size_t tail = tail_.fetch_sub(1, std::memory_order_acq_rel) - 1;
        LOG_DEBUG("  AFTER fetch_sub: tail=%zu (was %zu)\n", tail, tail_before);

        if (entries_.empty()) {
            LOG_ERROR("Stack corruption in trampoline: entries_ is EMPTY!\n");
            LOG_ERROR("  tail_before=%zu, entries_.size()=%zu\n", tail_before, entries_size);
            LOG_ERROR("  this=%p\n", (void*)this);
            std::abort();
        }

        if (tail >= entries_.size()) {
            LOG_ERROR("Stack corruption in trampoline: tail >= entries_.size()!\n");
            LOG_ERROR("  tail=%zu, entries_.size()=%zu, tail_before=%zu\n",
                      tail, entries_.size(), tail_before);
            LOG_ERROR("  this=%p\n", (void*)this);
            std::abort();
        }

        auto& entry = entries_[tail];
        LOG_DEBUG("  entry[%zu]: ip=0x%lx, return_address=0x%lx, location=%p, stack_pointer=0x%lx\n",
                  tail, (unsigned long)entry.ip, (unsigned long)entry.return_address,
                  (void*)entry.location, (unsigned long)entry.stack_pointer);

        // Check for longjmp: if SP doesn't match expected, search backward
        // through shadow stack for matching entry (frames were skipped)
        if (sp != 0 && entry.stack_pointer != 0 && entry.stack_pointer != sp) {
            LOG_DEBUG("SP mismatch at index %zu: expected 0x%lx, got 0x%lx - checking for longjmp\n",
                      tail, (unsigned long)entry.stack_pointer, (unsigned long)sp);

            // Search backward through shadow stack for matching SP (nwind style)
            // Only update tail_ if we find a match - don't corrupt it during search
            for (size_t i = tail; i > 0; --i) {
                if (entries_[i - 1].stack_pointer == sp) {
                    LOG_DEBUG("longjmp detected: found matching SP at index %zu (skipped %zu frames)\n",
                              i - 1, tail - (i - 1));

                    // Update tail_ to skip all the frames that were bypassed by longjmp
                    tail_.store(i - 1, std::memory_order_release);
                    tail = i - 1;
                    break;
                }
            }
            // If no match found, continue with current entry (SP calculation may differ by platform)
        }

        // Verify epoch hasn't changed (reset wasn't called during our execution)
        uint64_t final_epoch = epoch_.load(std::memory_order_acquire);
        if (final_epoch != current_epoch) {
            LOG_ERROR("Reset detected during trampoline - aborting\n");
            LOG_ERROR("  current_epoch=%lu, final_epoch=%lu\n",
                      (unsigned long)current_epoch, (unsigned long)final_epoch);
            std::abort();
        }

        uintptr_t ret_addr = entries_[tail].return_address;
        LOG_DEBUG("  Returning to address 0x%lx\n", (unsigned long)ret_addr);
        LOG_DEBUG("=== on_ret_trampoline EXIT ===\n");
        return ret_addr;
    }

private:
    /**
     * Copy cached frames to output buffer (fast path).
     *
     * Called when trampolines are already installed and we can read
     * directly from the shadow stack.
     */
    size_t copy_cached_frames(void** buffer, size_t max_frames) {
        size_t tail = tail_.load(std::memory_order_acquire);
        size_t available = tail; // frames from 0 to tail-1
        size_t count = (available < max_frames) ? available : max_frames;

        for (size_t i = 0; i < count; ++i) {
            buffer[i] = reinterpret_cast<void*>(entries_[count - 1 - i].ip);
        }

        LOG_DEBUG("Fast path: %zu frames\n", count);
        return count;
    }

    // Capture frames using unwinder, install trampolines
    size_t capture_and_install(void** buffer, size_t max_frames) {
        LOG_DEBUG("=== capture_and_install ENTER ===\n");
        LOG_DEBUG("  this=%p, max_frames=%zu\n", (void*)this, max_frames);

        // First, capture IPs using the unwinder
        std::vector<void*> raw_frames(max_frames);
        size_t raw_count = do_unwind(raw_frames.data(), max_frames);
        LOG_DEBUG("  do_unwind returned %zu frames\n", raw_count);

        if (raw_count == 0) {
            LOG_DEBUG("  No frames captured, returning 0\n");
            return 0;
        }

        // Now walk the stack to get return address locations and install trampolines
        std::vector<StackEntry> new_entries;
        new_entries.reserve(raw_count);
        bool found_existing = false;

        unw_context_t ctx;
        unw_cursor_t cursor;
        unw_getcontext(&ctx);
        unw_init_local(&cursor, &ctx);
        LOG_DEBUG("  Initialized libunwind cursor\n");

        // Skip the current frame to avoid patching our own return address
        if (unw_step(&cursor) > 0) {
            // Skipped internal frame
        }

        // Process frames: read current frame, then step to next
        // Note: After skip loop, cursor is positioned AT the first frame we want
        // We need to read first, then step (not step-then-read)
        size_t frame_idx = 0;
        int step_result;
        do {
            if (frame_idx >= raw_count) break;

            unw_word_t ip, sp;
            unw_get_reg(&cursor, UNW_REG_IP, &ip);
            unw_get_reg(&cursor, GS_SP_REGISTER, &sp);

            // On ARM64, strip PAC (Pointer Authentication Code) bits from IP.
            // PAC-signed addresses have authentication bits in the upper bits
            // that must be stripped for valid address comparison and symbolization.
#ifdef GS_ARCH_AARCH64
            ip = ptrauth_strip(ip);
#endif

            // On ARM64 Linux, unw_backtrace returns addresses adjusted by -1
            // (to point inside the call instruction for symbolization),
            // but unw_get_reg(UNW_REG_IP) returns the raw return address.
            // Adjust to match unw_backtrace's behavior for consistency.
#if defined(GS_ARCH_AARCH64) && defined(__linux__)
            if (ip > 0) {
                ip = ip - 1;
            }
#endif

            // Get location where return address is stored
            uintptr_t* ret_loc = nullptr;
#ifdef __linux__
            unw_save_loc_t loc;
            if (unw_get_save_loc(&cursor, GS_RA_REGISTER, &loc) == 0 &&
                loc.type == UNW_SLT_MEMORY) {
                ret_loc = reinterpret_cast<uintptr_t*>(loc.u.addr);
            }
#else
            // macOS: return address is at fp + sizeof(void*)
            ret_loc = reinterpret_cast<uintptr_t*>(sp + sizeof(void*));
#endif
            if (!ret_loc) break;

            uintptr_t ret_addr = *ret_loc;

            // Strip PAC (Pointer Authentication Code) if present.
            // On ARM64 with PAC, return addresses have authentication bits
            // that must be stripped before comparison or storage.
            uintptr_t stripped_ret_addr = ptrauth_strip(ret_addr);

            // Check if already patched (cache hit)
            // Compare against stripped address since trampoline address doesn't have PAC
            if (stripped_ret_addr == reinterpret_cast<uintptr_t>(ghost_ret_trampoline)) {
                found_existing = true;
                LOG_DEBUG("Found existing trampoline at frame %zu\n", frame_idx);
                break;
            }

            // Store the stack pointer that the trampoline will pass.
            // Linux: libunwind's SP matches what the trampoline passes
            // macOS: trampoline passes ret_loc + sizeof(void*), NOT libunwind's SP
#ifdef __APPLE__
            uintptr_t expected_sp = reinterpret_cast<uintptr_t>(ret_loc) + sizeof(void*);
#else
            unw_word_t actual_sp;
            unw_get_reg(&cursor, UNW_REG_SP, &actual_sp);
            uintptr_t expected_sp = static_cast<uintptr_t>(actual_sp);
#endif
            // Store both IP (for returning to caller) and return_address (for trampoline restoration)
            // Insert at beginning to reverse order (oldest at index 0, newest at end)
            new_entries.insert(new_entries.begin(), {ip, ret_addr, ret_loc, expected_sp});
            frame_idx++;

            step_result = unw_step(&cursor);
        } while (step_result > 0);

        LOG_DEBUG("  Collected %zu new entries, found_existing=%d\n", new_entries.size(), (int)found_existing);

        // Install trampolines on new entries
        LOG_DEBUG("  Installing trampolines (trampoline addr=%p):\n", (void*)ghost_ret_trampoline);
        for (size_t i = 0; i < new_entries.size(); ++i) {
            auto& e = new_entries[i];
            LOG_DEBUG("    [%zu] location=%p, old_value=0x%lx, ip=0x%lx, expected_sp=0x%lx\n",
                      i, (void*)e.location, (unsigned long)*e.location,
                      (unsigned long)e.ip, (unsigned long)e.stack_pointer);
            *e.location = reinterpret_cast<uintptr_t>(ghost_ret_trampoline);
        }

        // Merge with existing entries if we found a patched frame
        if (found_existing && !entries_.empty()) {
            size_t tail = tail_.load(std::memory_order_acquire);
            LOG_DEBUG("  Merging with %zu existing entries\n", tail);
            // With reversed order, entries below tail are still valid
            // Insert existing valid entries at the beginning of new_entries
            new_entries.insert(new_entries.begin(),
                               entries_.begin(),
                               entries_.begin() + tail);
        }

        entries_ = std::move(new_entries);
        tail_.store(entries_.size(), std::memory_order_release);
        trampolines_installed_ = true;

        LOG_DEBUG("  Final state: entries_.size()=%zu, tail_=%zu\n",
                  entries_.size(), tail_.load(std::memory_order_acquire));

        // Copy to output buffer - return the IP of each frame (what unw_backtrace returns)
        // Reverse order: newest frame at buffer[0], oldest at buffer[count-1]
        size_t count = (entries_.size() < max_frames) ? entries_.size() : max_frames;
        for (size_t i = 0; i < count; ++i) {
            buffer[i] = reinterpret_cast<void*>(entries_[count - 1 - i].ip);
        }

        LOG_DEBUG("=== capture_and_install EXIT, returning %zu frames ===\n", count);
        return count;
    }

    // Call the unwinder (custom or default)
    size_t do_unwind(void** buffer, size_t max_frames) {
        if (custom_unwinder_) {
            return custom_unwinder_(buffer, max_frames);
        }

#ifdef __APPLE__
        // macOS: use standard backtrace function
        int ret = ::backtrace(buffer, static_cast<int>(max_frames));
        return (ret > 0) ? static_cast<size_t>(ret) : 0;
#else
        // Linux: use libunwind's unw_backtrace
        int ret = unw_backtrace(buffer, static_cast<int>(max_frames));
        return (ret > 0) ? static_cast<size_t>(ret) : 0;
#endif
    }

    // Shadow stack entries (return addresses and their locations)
    std::vector<StackEntry> entries_;

    // Current position in the shadow stack (atomic for signal safety)
    std::atomic<size_t> tail_{0};

    // Epoch counter - incremented on reset to invalidate in-flight operations
    std::atomic<uint64_t> epoch_{0};

    // Guards against recursive calls (e.g., from signal handlers during capture)
    bool is_capturing_ = false;

    // Whether trampolines are currently installed
    bool trampolines_installed_ = false;

    // Optional custom unwinder function
    ghost_stack_unwinder_t custom_unwinder_ = nullptr;
};

// ============================================================================
// Thread-Local Instance Management
// ============================================================================

/**
 * RAII wrapper for thread-local GhostStackImpl.
 *
 * When a thread exits, C++ automatically calls this destructor which resets
 * the shadow stack (restoring original return addresses). This matches nwind's
 * approach using pthread_key_t destructors, but uses idiomatic C++11.
 */
struct ThreadLocalInstance {
    GhostStackImpl* ptr = nullptr;

    ~ThreadLocalInstance() {
        if (ptr) {
            LOG_DEBUG("Thread exit: resetting shadow stack\n");
            ptr->reset();
            delete ptr;
            ptr = nullptr;
        }
    }
};

static thread_local ThreadLocalInstance t_instance;

static GhostStackImpl& get_instance() {
    if (!t_instance.ptr) {
        t_instance.ptr = new GhostStackImpl();
        LOG_DEBUG("Created new shadow stack instance for thread: this=%p, tid=%lu\n",
                  (void*)t_instance.ptr, (unsigned long)pthread_self());
    }
    return *t_instance.ptr;
}

// ============================================================================
// Global State
// ============================================================================

static std::once_flag g_init_flag;
static std::once_flag g_atfork_flag;
static ghost_stack_unwinder_t g_custom_unwinder = nullptr;

// ============================================================================
// Fork Safety
// ============================================================================

/**
 * Called in child process after fork() to reset thread-local state.
 *
 * After fork(), the child process has a copy of the parent's shadow stack
 * entries. The virtual addresses are identical, so entries point to valid
 * locations in the child's own stack. We must restore the original return
 * addresses before the child returns through any trampolined frames.
 */
static void fork_child_handler() {
    if (t_instance.ptr) {
        t_instance.ptr->reset();
    }
    LOG_DEBUG("Fork child handler: reset shadow stack\n");
}

static void register_atfork_handler() {
    std::call_once(g_atfork_flag, []() {
        pthread_atfork(nullptr, nullptr, fork_child_handler);
        LOG_DEBUG("Registered pthread_atfork handler\n");
    });
}

// ============================================================================
// C API Implementation
// ============================================================================

extern "C" {

void ghost_stack_init(ghost_stack_unwinder_t unwinder) {
    std::call_once(g_init_flag, [unwinder]() {
        g_custom_unwinder = unwinder;
        LOG_DEBUG("Initialized with %s unwinder\n",
                  unwinder ? "custom" : "default");
    });

    // Register fork handler (idempotent, safe to call multiple times)
    register_atfork_handler();
}

size_t ghost_stack_backtrace(void** buffer, size_t size) {
    // Auto-init if needed
    std::call_once(g_init_flag, []() {
        g_custom_unwinder = nullptr;
    });

    // Ensure fork handler is registered (idempotent)
    register_atfork_handler();

    auto& impl = get_instance();

    // Apply global unwinder setting if not already set
    static thread_local bool unwinder_set = false;
    if (!unwinder_set) {
        impl.set_unwinder(g_custom_unwinder);
        unwinder_set = true;
    }

    return impl.backtrace(buffer, size);
}

void ghost_stack_reset(void) {
    if (t_instance.ptr) {
        t_instance.ptr->reset();
    }
}

void ghost_stack_thread_cleanup(void) {
    if (t_instance.ptr) {
        t_instance.ptr->reset();
        delete t_instance.ptr;
        t_instance.ptr = nullptr;
    }
}

// Called by assembly trampoline
uintptr_t ghost_trampoline_handler(uintptr_t sp) {
    LOG_DEBUG(">>> ghost_trampoline_handler called, sp=0x%lx, tid=%lu\n",
              (unsigned long)sp, (unsigned long)pthread_self());
    auto& impl = get_instance();
    LOG_DEBUG(">>> got instance=%p\n", (void*)&impl);
    uintptr_t result = impl.on_ret_trampoline(sp);
    LOG_DEBUG(">>> ghost_trampoline_handler returning 0x%lx\n", (unsigned long)result);
    return result;
}

// Called when exception passes through trampoline
uintptr_t ghost_exception_handler(void* exception) {
    LOG_DEBUG("Exception through trampoline\n");

    auto& impl = get_instance();
    uintptr_t ret = impl.pop_entry();  // Direct pop, no longjmp check
    impl.reset();

    __cxxabiv1::__cxa_begin_catch(exception);
    return ret;
}

} // extern 
