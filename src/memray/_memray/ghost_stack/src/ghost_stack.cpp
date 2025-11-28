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

#ifdef DEBUG
#define LOG_DEBUG(...) do { fprintf(stderr, "[GhostStack] " __VA_ARGS__); fflush(stderr); } while(0)
#else
#define LOG_DEBUG(...) ((void)0)
#endif

#define LOG_ERROR(...) do { fprintf(stderr, "[GhostStack][ERROR] " __VA_ARGS__); fflush(stderr); } while(0)

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
    uintptr_t* location;        // Where return address lives on the stack
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
            LOG_DEBUG("backtrace: recursive call, bailing out\n");
            return 0;  // Recursive call, bail out
        }
        is_capturing_ = true;

        size_t result = 0;

        // Always use capture_and_install - it handles both cases:
        // 1. No trampolines installed: full capture + install
        // 2. Trampolines installed: capture new frames up to trampoline, merge with cached
        LOG_DEBUG("backtrace: capture_and_install (trampolines_installed=%d, entries=%zu)\n",
                  trampolines_installed_, entries_.size());
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
            size_t loc = location_.load(std::memory_order_acquire);
            for (size_t i = loc; i < entries_.size(); ++i) {
                *entries_[i].location = entries_[i].return_address;
            }
        }
        clear_entries();
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
        location_.store(0, std::memory_order_release);
        trampolines_installed_ = false;
    }

public:

    /**
     * Called by trampoline when a function returns.
     *
     * Uses epoch-based validation to detect if reset() was called during
     * execution (e.g., from a signal handler). This prevents accessing
     * stale or cleared entries.
     *
     * Implements longjmp detection by comparing the current stack pointer
     * against the expected value. If they don't match, searches forward
     * through the shadow stack to find the matching entry (like nwind does).
     *
     * @param sp  Stack pointer at return time (for longjmp detection)
     * @return    Original return address to jump to
     */
    uintptr_t on_ret_trampoline(uintptr_t sp) {
        // Capture current epoch - if it changes, reset() was called
        uint64_t current_epoch = epoch_.load(std::memory_order_acquire);

        size_t loc = location_.load(std::memory_order_acquire);

        if (entries_.empty() || loc >= entries_.size()) {
            LOG_ERROR("Stack corruption in trampoline!\n");
            std::abort();
        }

        auto& entry = entries_[loc];

        // Check for longjmp: if SP doesn't match expected, search forward
        // through shadow stack for matching entry (frames were skipped)
        if (sp != 0 && entry.stack_pointer != 0 && entry.stack_pointer != sp) {
            LOG_DEBUG("SP mismatch at index %zu: expected 0x%lx, got 0x%lx - checking for longjmp\n",
                      loc, entry.stack_pointer, sp);

            // Search forward through shadow stack for matching SP
            bool found = false;
            for (size_t i = loc + 1; i < entries_.size(); ++i) {
                if (entries_[i].stack_pointer == sp) {
                    LOG_DEBUG("longjmp detected: found matching SP at index %zu (skipped %zu frames)\n",
                              i, i - loc);

                    // Don't restore return addresses for skipped frames - they no longer
                    // exist on the stack after longjmp. Just skip over them.
                    loc = i;
                    location_.store(loc, std::memory_order_release);
                    found = true;
                    break;
                }
            }

            if (!found) {
                // No matching entry found - this could be:
                // 1. A bug in our SP calculation
                // 2. Stack corruption
                // 3. Some other unexpected scenario
                // For now, log and continue with the expected entry
                LOG_DEBUG("No matching SP found in shadow stack - continuing with current entry\n");
            }
        }

        // Verify epoch hasn't changed (reset wasn't called during our execution)
        if (epoch_.load(std::memory_order_acquire) != current_epoch) {
            LOG_ERROR("Reset detected during trampoline - aborting\n");
            std::abort();
        }

        // Re-read location in case it was updated during longjmp handling
        loc = location_.load(std::memory_order_acquire);
        uintptr_t ret_addr = entries_[loc].return_address;
        location_.fetch_add(1, std::memory_order_acq_rel);
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
        size_t loc = location_.load(std::memory_order_acquire);
        size_t available = entries_.size() - loc;
        size_t count = (available < max_frames) ? available : max_frames;

        LOG_DEBUG("Fast path: loc=%zu, entries_.size()=%zu, available=%zu, count=%zu\n",
                  loc, entries_.size(), available, count);

        for (size_t i = 0; i < count; ++i) {
            buffer[i] = reinterpret_cast<void*>(entries_[loc + i].ip);
        }

        LOG_DEBUG("Fast path: returning %zu frames\n", count);
        return count;
    }

    // Capture frames using unwinder, install trampolines
    size_t capture_and_install(void** buffer, size_t max_frames) {
        // First, capture IPs using the unwinder
        std::vector<void*> raw_frames(max_frames);
        size_t raw_count = do_unwind(raw_frames.data(), max_frames);

        LOG_DEBUG("capture_and_install: raw_count=%zu from unwinder\n", raw_count);

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

        // Skip internal frames (platform-specific due to backtrace/libunwind differences)
#ifdef __APPLE__
        // macOS: Skip fewer frames due to backtrace()/libunwind difference
        for (int i = 0; i < 1 && unw_step(&cursor) > 0; ++i) {}
#else
        // Linux: Skip internal frames (this function + backtrace)
        for (int i = 0; i < 3 && unw_step(&cursor) > 0; ++i) {}
#endif

        size_t frame_idx = 0;
        LOG_DEBUG("capture_and_install: walking stack frames (raw_count=%zu)...\n", raw_count);
        LOG_DEBUG("capture_and_install: Comparing raw vs walked frames:\n");

        // Process frames: read current frame, then step to next
        // Note: After skip loop, cursor is positioned AT the first frame we want
        // We need to read first, then step (not step-then-read)
        int step_result;
        do {
            if (frame_idx >= raw_count) break;

            unw_word_t ip, sp;
            unw_get_reg(&cursor, UNW_REG_IP, &ip);
            unw_get_reg(&cursor, GS_SP_REGISTER, &sp);

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
            if (!ret_loc) {
                LOG_DEBUG("  frame %zu: ret_loc is NULL, stopping\n", frame_idx);
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
                LOG_DEBUG("  frame %zu: Found existing trampoline (ip=0x%lx)\n", frame_idx, (unsigned long)ip);
                break;
            }

            LOG_DEBUG("  frame %zu: ip=0x%lx, ret_addr=0x%lx, ret_loc=%p\n",
                      frame_idx, (unsigned long)ip, (unsigned long)ret_addr, (void*)ret_loc);

            // Store the stack pointer that the trampoline will pass.
            // The trampoline passes RSP right after landing (before its stack manipulations).
            // When RET executes, it pops the return address, so:
            //   RSP_trampoline = ret_loc + sizeof(void*)
            // This allows longjmp detection by comparing against the stored value.
            uintptr_t expected_sp = reinterpret_cast<uintptr_t>(ret_loc) + sizeof(void*);
            // Store both IP (for returning to caller) and return_address (for trampoline restoration)
            new_entries.push_back({ip, ret_addr, ret_loc, expected_sp});
            frame_idx++;

            step_result = unw_step(&cursor);
        } while (step_result > 0);
        LOG_DEBUG("capture_and_install: walked %zu frames, found_existing=%d\n", frame_idx, found_existing);

        // Install trampolines on new entries
        LOG_DEBUG("capture_and_install: installing %zu trampolines\n", new_entries.size());
        for (auto& e : new_entries) {
            *e.location = reinterpret_cast<uintptr_t>(ghost_ret_trampoline);
        }

        // Merge with existing entries if we found a patched frame
        if (found_existing && !entries_.empty()) {
            size_t loc = location_.load(std::memory_order_acquire);
            LOG_DEBUG("capture_and_install: merging with existing entries (loc=%zu, existing entries=%zu)\n",
                      loc, entries_.size());
            new_entries.insert(new_entries.end(),
                               entries_.begin() + static_cast<long>(loc),
                               entries_.end());
            LOG_DEBUG("capture_and_install: after merge, total entries=%zu\n", new_entries.size());
        }

        entries_ = std::move(new_entries);
        location_.store(0, std::memory_order_release);
        trampolines_installed_ = true;

        // Copy to output buffer - return the IP of each frame (what unw_backtrace returns)
        size_t count = (entries_.size() < max_frames) ? entries_.size() : max_frames;
        for (size_t i = 0; i < count; ++i) {
            buffer[i] = reinterpret_cast<void*>(entries_[i].ip);
        }

        LOG_DEBUG("Captured %zu frames (total entries=%zu)\n", count, entries_.size());
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
        size_t count = (ret > 0) ? static_cast<size_t>(ret) : 0;
        LOG_DEBUG("do_unwind: unw_backtrace returned %zu frames\n", count);
        for (size_t i = 0; i < count && i < 10; ++i) {
            LOG_DEBUG("  raw frame %zu: ip=%p\n", i, buffer[i]);
        }
        return count;
#endif
    }

    // Shadow stack entries (return addresses and their locations)
    std::vector<StackEntry> entries_;

    // Current position in the shadow stack (atomic for signal safety)
    std::atomic<size_t> location_{0};

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

// Global counter for debugging
static std::atomic<int> g_backtrace_call_count{0};

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
            LOG_DEBUG("Thread exit: resetting shadow stack (total backtrace calls: %d)\n",
                      g_backtrace_call_count.load());
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
        LOG_DEBUG("Created new shadow stack instance for thread\n");
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
    LOG_DEBUG("ghost_stack_init called\n");
    std::call_once(g_init_flag, [unwinder]() {
        g_custom_unwinder = unwinder;
        LOG_DEBUG("Initialized with %s unwinder\n",
                  unwinder ? "custom" : "default");
    });

    // Register fork handler (idempotent, safe to call multiple times)
    register_atfork_handler();
}

size_t ghost_stack_backtrace(void** buffer, size_t size) {
    int call_num = g_backtrace_call_count.fetch_add(1) + 1;
    LOG_DEBUG("ghost_stack_backtrace called (call #%d, size=%zu)\n", call_num, size);

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

    size_t result = impl.backtrace(buffer, size);
    LOG_DEBUG("ghost_stack_backtrace returning %zu frames (call #%d)\n", result, call_num);
    return result;
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
    LOG_DEBUG("Exception through trampoline\n");

    uintptr_t ret = get_instance().on_ret_trampoline(0);
    get_instance().reset();

    __cxxabiv1::__cxa_begin_catch(exception);
    return ret;
}

} // extern "C"
