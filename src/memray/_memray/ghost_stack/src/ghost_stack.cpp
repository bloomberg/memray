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
extern "C" void ghost_ret_trampoline();

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

// #define DEBUG
#ifdef DEBUG
#define LOG_DEBUG(...) do { fprintf(stderr, "[GS] " __VA_ARGS__); fflush(stderr); } while(0)
#else
#define LOG_DEBUG(...) ((void)0)
#endif

#define LOG_ERROR(...) do { fprintf(stderr, "[GS][ERR] " __VA_ARGS__); fflush(stderr); } while(0)

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
        if (is_capturing_) {
            return 0;  // Recursive call, bail out
        }
        is_capturing_ = true;

        size_t result = 0;

        // Fast path: trampolines installed, return cached frames
        if (trampolines_installed_ && !entries_.empty()) {
            result = copy_cached_frames(buffer, max_frames);
            is_capturing_ = false;
            return result;
        }

        // Slow path: capture with unwinder and install trampolines
        result = capture_and_install(buffer, max_frames);
        is_capturing_ = false;
        return result;
    }

    /**
     * Reset the shadow stack, restoring all original return addresses.
     *
     * This is the normal reset path - it restores the original return addresses
     * to the stack before clearing the shadow stack entries.
     */
    void reset() {
        if (trampolines_installed_) {
            size_t tail = tail_.load(std::memory_order_acquire);
            // With reversed order, iterate from 0 to tail (all entries below tail)
            for (size_t i = 0; i < tail; ++i) {
                *entries_[i].location = entries_[i].return_address;
            }
        }
        clear_entries();
    }

public:
    /**
     * Direct entry access method for exception handling.
     * Decrements tail and returns the return address without longjmp checking.
     */
    uintptr_t pop_entry() {
        size_t tail = tail_.fetch_sub(1, std::memory_order_acq_rel) - 1;
        if (tail >= entries_.size()) {
            LOG_ERROR("Stack corruption in pop_entry!\n");
            std::abort();
        }
        return entries_[tail].return_address;
    }

private:
    /**
     * Internal helper to clear all state.
     * Increments epoch to invalidate any in-flight trampoline operations.
     */
    void clear_entries() {
        // Increment epoch FIRST to signal any in-flight operations
        epoch_.fetch_add(1, std::memory_order_release);

        entries_.clear();
        tail_.store(0, std::memory_order_release);
        trampolines_installed_ = false;
    }

public:

    /**
     * Called by trampoline when a function returns.
     */
    uintptr_t on_ret_trampoline(uintptr_t sp) {
        // Capture current epoch - if it changes, reset() was called
        uint64_t current_epoch = epoch_.load(std::memory_order_acquire);

        // Decrement tail first, like nwind does
        size_t tail = tail_.fetch_sub(1, std::memory_order_acq_rel) - 1;

        if (entries_.empty() || tail >= entries_.size()) {
            LOG_ERROR("CORRUPTION! empty=%d tail=%zu sz=%zu\n",
                      (int)entries_.empty(), tail, entries_.size());
            std::abort();
        }

        auto& entry = entries_[tail];

        // Check for longjmp: if SP doesn't match expected, search backward
        // through shadow stack for matching entry (frames were skipped)
        if (sp != 0 && entry.stack_pointer != 0 && entry.stack_pointer != sp) {
            // Search backward through shadow stack for matching SP (nwind style)
            // Only update tail_ if we find a match - don't corrupt it during search
            for (size_t i = tail; i > 0; --i) {
                if (entries_[i - 1].stack_pointer == sp) {
                    // Update tail_ to skip all the frames that were bypassed by longjmp
                    tail_.store(i - 1, std::memory_order_release);
                    tail = i - 1;
                    break;
                }
            }
            // If no match found, continue with current entry (SP calculation may differ by platform)
        }

        // Verify epoch hasn't changed (reset wasn't called during our execution)
        if (epoch_.load(std::memory_order_acquire) != current_epoch) {
            LOG_ERROR("Reset detected during trampoline - aborting\n");
            std::abort();
        }

        return entries_[tail].return_address;
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

        return count;
    }

    // Capture frames using unwinder, install trampolines
    size_t capture_and_install(void** buffer, size_t max_frames) {
        // First, capture IPs using the unwinder
        std::vector<void*> raw_frames(max_frames);
        size_t raw_count = do_unwind(raw_frames.data(), max_frames);

        if (raw_count == 0) {
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

        // Skip the current frame to avoid patching our own return address
        if (unw_step(&cursor) > 0) {
            // Skipped internal frame
        }

        // Process frames: read current frame, then step to next
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

            // Get actual SP (needed for ARM64 expected_sp calculation)
            unw_word_t actual_sp;
            unw_get_reg(&cursor, UNW_REG_SP, &actual_sp);

#ifdef __linux__
            unw_save_loc_t loc;
            int save_loc_ret = unw_get_save_loc(&cursor, GS_RA_REGISTER, &loc);

            if (save_loc_ret == 0 && loc.type == UNW_SLT_MEMORY && loc.u.addr != 0) {
                ret_loc = reinterpret_cast<uintptr_t*>(loc.u.addr);
                // Sanity check: ret_loc should be somewhere near FP (which is our sp variable)
                uintptr_t addr = loc.u.addr;
                if (addr < sp - 0x10000 || addr > sp + 0x10000) {
                    ret_loc = nullptr;  // Don't use this suspicious address
                }
            }
#else
            // macOS: return address is at fp + sizeof(void*)
            ret_loc = reinterpret_cast<uintptr_t*>(sp + sizeof(void*));
#endif

            if (!ret_loc) {
                break;
            }

            uintptr_t ret_addr = *ret_loc;

            // Strip PAC (Pointer Authentication Code) if present.
            // On ARM64 with PAC, return addresses have authentication bits
            // that must be stripped before comparison or storage.
            uintptr_t stripped_ret_addr = ptrauth_strip(ret_addr);

            // Check if already patched (cache hit)
            // Compare against stripped address since trampoline address doesn't have PAC
            if (stripped_ret_addr == reinterpret_cast<uintptr_t>(ghost_ret_trampoline)) {
                found_existing = true;
                break;
            }

            // Store the stack pointer that the trampoline will pass.
            // This allows longjmp detection by comparing against the stored value.
            //
            // On x86_64: RET pops return address, so trampoline sees ret_loc + 8
            // On ARM64:  RET doesn't touch SP. The trampoline receives the actual SP
            //            at the moment of return (after the function's epilogue ran).
            //            This is the value from UNW_REG_SP, not the FP (UNW_AARCH64_X29).
#ifdef GS_ARCH_AARCH64
            uintptr_t expected_sp = actual_sp;  // Actual SP at this frame
#else
            uintptr_t expected_sp = reinterpret_cast<uintptr_t>(ret_loc) + sizeof(void*);
#endif

            // Store both IP (for returning to caller) and return_address (for trampoline restoration)
            // Insert at beginning to reverse order (oldest at index 0, newest at end)
            new_entries.insert(new_entries.begin(), {ip, ret_addr, ret_loc, expected_sp});
            frame_idx++;

            step_result = unw_step(&cursor);
        } while (step_result > 0);

        // Install trampolines on new entries
        uintptr_t tramp_addr = reinterpret_cast<uintptr_t>(ghost_ret_trampoline);
        for (size_t i = 0; i < new_entries.size(); ++i) {
            auto& e = new_entries[i];
            *e.location = tramp_addr;
        }

        // Merge with existing entries if we found a patched frame
        if (found_existing && !entries_.empty()) {
            size_t tail = tail_.load(std::memory_order_acquire);
            // With reversed order, entries below tail are still valid
            // Insert existing valid entries at the beginning of new_entries
            new_entries.insert(new_entries.begin(),
                               entries_.begin(),
                               entries_.begin() + tail);
        }

        entries_ = std::move(new_entries);
        tail_.store(entries_.size(), std::memory_order_release);
        trampolines_installed_ = true;

        // Copy to output buffer - return the IP of each frame (what unw_backtrace returns)
        size_t count = (entries_.size() < max_frames) ? entries_.size() : max_frames;
        for (size_t i = 0; i < count; ++i) {
            buffer[i] = reinterpret_cast<void*>(entries_[count - 1 - i].ip);
        }

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
}

static void register_atfork_handler() {
    std::call_once(g_atfork_flag, []() {
        pthread_atfork(nullptr, nullptr, fork_child_handler);
    });
}

// ============================================================================
// C API Implementation
// ============================================================================

extern "C" {

void ghost_stack_init(ghost_stack_unwinder_t unwinder) {
    std::call_once(g_init_flag, [unwinder]() {
        g_custom_unwinder = unwinder;
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
    return get_instance().on_ret_trampoline(sp);
}

// Called when exception passes through trampoline
uintptr_t ghost_exception_handler(void* exception) {
    auto& impl = get_instance();
    uintptr_t ret = impl.pop_entry();  // Direct pop, no longjmp check
    impl.reset();

    __cxxabiv1::__cxa_begin_catch(exception);
    return ret;
}

} // extern "C"
